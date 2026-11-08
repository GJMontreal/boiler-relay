import logging
from dataclasses import asdict
from datetime import datetime, timezone
from json import loads
from threading import Event, Thread
from time import monotonic, sleep

from redis import Redis

from boiler_relay.heating_cooling_state import HeatingCoolingState
from boiler_relay.outputs import create_output
from boiler_relay.pid import PID
from boiler_relay.state_publisher import ACTIVE, SHADOW, StatePublisher

log = logging.getLogger(__name__)

STALE_AFTER = 2 * 60 * 60
FAILURE_LIMIT = 3
REPORT_EVERY = 12
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

class Zone(Thread):
    def __init__(self, zone_config, redis_config, mqtt_config, mode=ACTIVE):
        super().__init__(name=zone_config.name)
        self.input_path = zone_config.sensor_path
        self.output_path = zone_config.control_path
        self.redis = Redis(host=redis_config.host, port=redis_config.port, db=0)
        self.shadow = mode == SHADOW
        self.publisher = StatePublisher(self.redis, mode)
        self.system = zone_config.system
        self.has_end_switch = bool(zone_config.end_switches)

        self.gains = zone_config.pid
        self.pid = PID(self.gains.kp, self.gains.ki, self.gains.kd,
                       integral_cap=self.gains.integral_cap,
                       sample_time=zone_config.pid_interval)

        self.interval = 5
        self.cycle = 0
        self.duration = zone_config.control_interval * 60 / self.interval

        self.outputs = []
        if not self.shadow:
            self.outputs = [create_output({**output, "active_low": zone_config.active_low}, mqtt_config)
                            for output in zone_config.outputs]

        self.control_value = 0.0
        self.target_temperature = 0.0
        self.current_temperature = None
        self.last_sample_time = None
        self.last_change_at = None
        self.state = None
        self.failures = 0
        self.warned = set()
        self.stopping = Event()
        self.window_ticks = 0
        self.window_on = 0
        self.window_control = 0.0

    def start(self):
        for output in self.outputs:
            output.start()
        super().start()

    def run(self):
        while not self.stopping.is_set():
            try:
                self.update()
                if self.failures:
                    log.info("zone %s recovered after %d failed ticks", self.name, self.failures)
                self.failures = 0
            except Exception as error:
                self.failures += 1
                self.report_failure(error)
                if self.failures >= FAILURE_LIMIT:
                    self.deactivate_outputs()
            sleep(self.interval)

    def shutdown(self):
        self.stopping.set()
        if self.is_alive():
            self.join(timeout=self.interval * 2)
        self.deactivate_outputs(wait=True)
        for output in self.outputs:
            output.stop()

    def deactivate_outputs(self, wait=False):
        for output in self.outputs:
            try:
                output.deactivate(wait=wait)
            except Exception as error:
                log.error("zone %s could not drive an output inactive: %s", self.name, error)

    def report_failure(self, error):
        if self.failures in (1, FAILURE_LIMIT) or self.failures % REPORT_EVERY == 0:
            log.error("zone %s tick failed %d times in a row: %s", self.name, self.failures, error)

    def warn(self, key, message):
        if key in self.warned:
            return False
        self.warned.add(key)
        log.warning("zone %s: %s", self.name, message)
        return True

    def clear(self, key):
        if key in self.warned:
            self.warned.discard(key)
            log.info("zone %s: %s is back to normal", self.name, key)

    def update(self):
        self.read_sensors()
        self.control_value = self.compute_control_value()
        if not self.shadow:
            self.redis.set(self.output_path, self.control_value)

        target_state = self.read_target_state()
        if target_state is None:
            self.publisher.zone(self.name, self.system, self.control_value, None, asdict(self.gains))
            return

        state = self.duty_state(target_state)
        for output in self.outputs:
            output.activate(state.value)

        if not self.shadow:
            topic = f'{self.input_path}/heating_cooling_state'
            self.redis.set(topic, state.value)
            self.redis.publish(topic, state.value)
        self.publisher.zone(self.name, self.system, self.control_value, state.value, asdict(self.gains))

        self.record(state)
        self.advance_cycle()

    def read_json(self, key):
        message = self.redis.get(key)
        if message is None:
            return None
        return loads(message)

    def read_sensors(self):
        data = self.read_json(f'{self.input_path}/current_temperature')
        if data is not None:
            self.current_temperature = float(data['value'])
            if data['time'] != self.last_sample_time:
                self.note_sample(data['time'])

        data = self.read_json(f'{self.input_path}/target_temperature')
        if data is not None:
            self.target_temperature = float(data['value'])

    def note_sample(self, sample_time):
        age = 0.0
        if self.last_sample_time is None:
            age = self.wall_clock_age(sample_time)
        self.last_sample_time = sample_time
        self.last_change_at = monotonic() - age

    def wall_clock_age(self, sample_time):
        try:
            reported = datetime.strptime(sample_time, TIME_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            self.warn("sample time", f"cannot read the sample time {sample_time!r}, treating the reading as fresh")
            return 0.0
        return max(0.0, (datetime.now(timezone.utc) - reported).total_seconds())

    def compute_control_value(self):
        if self.current_temperature is None:
            self.warn("sensor", "no temperature reading yet, calling for no heat")
            return 0.0
        if monotonic() - self.last_change_at > STALE_AFTER:
            if self.warn("sensor", f"temperature reading is stale since {self.last_sample_time}, calling for no heat"):
                self.pid.reset()
            return 0.0
        self.clear("sensor")
        self.pid.setpoint = self.target_temperature
        return self.pid(self.current_temperature)

    def read_target_state(self):
        message = self.redis.get(f'{self.input_path}/target_heatingcooling_state')
        if message is None:
            return None
        try:
            value = int(message.decode('utf-8'))
        except ValueError:
            value = None

        if value in (HeatingCoolingState.OFF.value, HeatingCoolingState.HEAT.value):
            self.clear("target state")
            return HeatingCoolingState(value)

        self.warn("target state", f"unsupported target state {message!r}, treating it as off")
        return HeatingCoolingState.OFF

    def duty_state(self, target_state):
        state = HeatingCoolingState.OFF
        on_time = int(self.control_value * self.duration)
        if target_state == HeatingCoolingState.HEAT and on_time > self.cycle:
            state = HeatingCoolingState.HEAT

        boost = self.read_json(f'{self.input_path}/boost')
        if boost == True:
            state = HeatingCoolingState.HEAT
        return state

    def record(self, state):
        if state != self.state:
            log.info("zone %s %s -> %s", self.name, self.state, state)
            self.state = state
        log.debug("zone %s control %.3f current %s target %s %s",
                  self.name, self.control_value, self.current_temperature, self.target_temperature, state)

        self.window_ticks += 1
        self.window_control += self.control_value
        if state == HeatingCoolingState.HEAT:
            self.window_on += 1

    def advance_cycle(self):
        self.cycle += 1
        if self.cycle > self.duration - 1:
            self.cycle = 0
            log.info("zone %s window control_mean=%.3f on_fraction=%.3f ticks=%d",
                     self.name,
                     self.window_control / self.window_ticks,
                     self.window_on / self.window_ticks,
                     self.window_ticks)
            self.window_ticks = 0
            self.window_on = 0
            self.window_control = 0.0

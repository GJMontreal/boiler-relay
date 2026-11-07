import csv
import os
from json import loads
from threading import Thread
from time import sleep

from redis import Redis
from simple_pid import PID

from src.actuator import create_output
from src.heating_cooling_state import HeatingCoolingState

LOG_PATH = "/tmp/ramdisk/boiler-relay"

Kp = 1
Ki = 0.01
Kd = 0.5

class Zone(Thread):
    def __init__(self, zone_config, redis_config, mqtt_config):
        super().__init__(name=zone_config.name)
        self.input_path = zone_config.sensor_path
        self.output_path = zone_config.control_path
        self.redis = Redis(host=redis_config.host, port=redis_config.port, db=0)
        self.pid = PID(Kp, Ki, Kd,
                       setpoint=0,
                       sample_time=zone_config.pid_interval,
                       output_limits=(0, 1))

        self.interval = 5
        self.cycle = 0
        self.duration = 10 * 60 / self.interval

        self.outputs = []
        for output in zone_config.outputs:
            output = {"active_low": zone_config.active_low, **output}
            actuator = create_output(output, mqtt_config)
            if actuator is not None:
                self.outputs.append(actuator)

        self.control_value = 0.0
        self.target_temperature = 0.0
        self.current_temperature = None
        self.last_sample_time = None

    def start(self):
        for output in self.outputs:
            output.start()
        super().start()

    def run(self):
        while True:
            self.update()
            sleep(self.interval)

    def update(self):
        self.read_sensors()
        self.control_value = self.compute_control_value()
        self.redis.set(self.output_path, self.control_value)

        target_state = self.read_target_state()
        if target_state is None:
            return

        state = self.duty_state(target_state)
        for output in self.outputs:
            output.activate(state.value)

        topic = f'{self.input_path}/heating_cooling_state'
        self.redis.set(topic, state.value)
        self.redis.publish(topic, state.value)

        print(f'zone {self.name} {self.control_value:.3f} {self.current_temperature} {self.target_temperature} {state}')

        self.cycle += 1
        if self.cycle > self.duration - 1:
            self.cycle = 0

        if self.last_sample_time is not None and os.path.isdir(LOG_PATH):
            self.write_row()

    def read_json(self, key):
        message = self.redis.get(key)
        if message is None:
            return None
        return loads(message)

    def read_sensors(self):
        data = self.read_json(f'{self.input_path}/current_temperature')
        if data is not None:
            self.current_temperature = float(data['value'])
            self.last_sample_time = data['time']

        data = self.read_json(f'{self.input_path}/target_temperature')
        if data is not None:
            self.target_temperature = float(data['value'])

    def compute_control_value(self):
        if self.current_temperature is None:
            return 0.0
        self.pid.setpoint = self.target_temperature
        return self.pid(self.current_temperature)

    def read_target_state(self):
        message = self.redis.get(f'{self.input_path}/target_heatingcooling_state')
        if message is None:
            return None
        return HeatingCoolingState(int(message.decode('utf-8')))

    def duty_state(self, target_state):
        state = HeatingCoolingState.OFF
        on_time = int(self.control_value * self.duration)
        if target_state != HeatingCoolingState.OFF and on_time > self.cycle:
            state = HeatingCoolingState.HEAT

        boost = self.read_json(f'{self.input_path}/boost')
        if boost == True:
            state = HeatingCoolingState.HEAT
        return state

    def write_row(self):
        p, i, d = self.pid.components

        current_temperature = '{:.1f}'.format(self.current_temperature)
        target_temperature = '{:.1f}'.format(self.target_temperature)
        control_value = '{:.0f}'.format(self.control_value * self.duration)

        p_formatted = '{:.6f}'.format(p)
        i_formatted = '{:.6f}'.format(i)
        d_formatted = '{:.6f}'.format(d)

        row = ([ self.last_sample_time,
                current_temperature,
                target_temperature,
                control_value,
                p_formatted,
                i_formatted,
                d_formatted])

        self.write_row_to_csv(row)

    def write_row_to_csv(self,row):
        file_name = os.path.split(self.name)[-1]
        file_path = f'{LOG_PATH}/{file_name}_pid.csv'
        with open(file_path,'a', newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=',',quoting=csv.QUOTE_NONE)
            writer.writerow(row)

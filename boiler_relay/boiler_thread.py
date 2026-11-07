import logging
from threading import Event, Thread
from time import sleep

from boiler_relay.gpio import GPIO
from boiler_relay.heating_cooling_state import HeatingCoolingState

log = logging.getLogger(__name__)

FAILURE_LIMIT = 3
REPORT_EVERY = 12


class BoilerThread(Thread):
    def __init__(self, boiler_config, input_gpio, publisher=None):
        super().__init__(name="boiler")
        self.output_gpio = boiler_config.output_gpio
        self.active_low = boiler_config.active_low
        self.interval = boiler_config.poll_interval
        self.input_gpio = input_gpio
        self.publisher = publisher
        self.stopping = Event()
        self.failures = 0
        self.call = None
        self.config_output()
        self.config_inputs()

    def config_output(self):
        log.info("configuring GPIO %s as output", self.output_gpio)
        GPIO.setup(self.output_gpio, GPIO.OUT)
        output = GPIO.LOW
        if self.active_low:
            output = GPIO.HIGH
        GPIO.output(self.output_gpio, output)
        GPIO.cleanup()

    def config_inputs(self):
        for gpio in self.input_gpio:
            log.info("configuring GPIO %s as input", gpio)
            GPIO.setup(gpio, GPIO.IN)

    def run(self):
        while not self.stopping.is_set():
            try:
                self.update()
                if self.failures:
                    log.info("boiler recovered after %d failed polls", self.failures)
                self.failures = 0
            except Exception as error:
                self.failures += 1
                self.report_failure(error)
                if self.failures >= FAILURE_LIMIT:
                    self.deactivate()
            sleep(self.interval)

    def update(self):
        states = [GPIO.input(gpio) for gpio in self.input_gpio]
        combined_state = 1 if any(states) else 0
        self.drive(combined_state)
        if self.publisher:
            self.publisher.boiler(combined_state)
            self.publisher.heartbeat()

        if combined_state != self.call:
            log.info("boiler call %s -> %s", self.call, combined_state)
            self.call = combined_state

    def drive(self, state):
        output_state = state
        if self.active_low:
            output_state = state * -1 + 1
        GPIO.output(self.output_gpio, output_state)

    def deactivate(self):
        try:
            self.drive(0)
        except Exception as error:
            log.error("boiler could not be driven inactive: %s", error)

    def report_failure(self, error):
        if self.failures in (1, FAILURE_LIMIT) or self.failures % REPORT_EVERY == 0:
            log.error("boiler poll failed %d times in a row: %s", self.failures, error)

    def shutdown(self):
        self.stopping.set()
        if self.is_alive():
            self.join(timeout=self.interval * 2)
        self.deactivate()


class ShadowBoilerThread(Thread):
    def __init__(self, boiler_config, zones, publisher):
        super().__init__(name="boiler")
        self.interval = boiler_config.poll_interval
        self.zones = zones
        self.publisher = publisher
        self.stopping = Event()
        self.failures = 0
        self.call = None

    def run(self):
        while not self.stopping.is_set():
            try:
                self.update()
                if self.failures:
                    log.info("shadow boiler recovered after %d failed polls", self.failures)
                self.failures = 0
            except Exception as error:
                self.failures += 1
                self.report_failure(error)
            sleep(self.interval)

    def update(self):
        combined_state = 1 if any(zone.has_end_switch and zone.state == HeatingCoolingState.HEAT
                                  for zone in self.zones) else 0
        self.publisher.boiler(combined_state)
        self.publisher.heartbeat()

        if combined_state != self.call:
            log.info("shadow boiler call %s -> %s", self.call, combined_state)
            self.call = combined_state

    def report_failure(self, error):
        if self.failures in (1, FAILURE_LIMIT) or self.failures % REPORT_EVERY == 0:
            log.error("shadow boiler poll failed %d times in a row: %s", self.failures, error)

    def shutdown(self):
        self.stopping.set()
        if self.is_alive():
            self.join(timeout=self.interval * 2)

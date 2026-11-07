from threading import Thread
from time import sleep

from boiler_relay.gpio import GPIO


class BoilerThread(Thread):
    def __init__(self, boiler_config, input_gpio):
        self.output_gpio = boiler_config.output_gpio
        self.active_low = boiler_config.active_low
        self.interval = boiler_config.control_interval
        self.input_gpio = input_gpio
        self.config_output()
        self.config_inputs()
        super().__init__()

    def config_output(self):
        print(f'configuring GPIO: {self.output_gpio} as Output')
        GPIO.setup(self.output_gpio, GPIO.OUT)
        output = GPIO.LOW
        if self.active_low:
            output = GPIO.HIGH
        GPIO.output(self.output_gpio, output)
        GPIO.cleanup()

    def config_inputs(self):
        for gpio in self.input_gpio:
            print(f'configuring GPIO: {gpio} as Input')
            GPIO.setup(gpio, GPIO.IN)

    def run(self):
        while True:
            states = [GPIO.input(gpio) for gpio in self.input_gpio]
            combined_state = 1 if any(states) else 0

            output_state = combined_state
            if self.active_low:
                output_state = combined_state * -1 + 1
            GPIO.output(self.output_gpio, output_state)

            print(f'boiler {combined_state}')
            sleep(self.interval)

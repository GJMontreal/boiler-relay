from boiler_relay.config import MQTTConfig
from boiler_relay.gpio import GPIO
from boiler_relay.outputs.actuator import Actuator

class GPIOOutput(Actuator):
  output_type = "gpio"

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    super().__init__(output_config, mqtt_config)
    self.pin = output_config["pin"]
    self.active_low = output_config.get("active_low", False)
    self.config_gpio()

  def config_gpio(self):
    print(f'configuring GPIO: {self.pin} as Output')
    GPIO.setup(self.pin, GPIO.OUT)
    output = GPIO.LOW
    if self.active_low:
      output = GPIO.HIGH
    GPIO.output(self.pin, output)
    GPIO.cleanup()

  def activate(self, value):
    output = 1 if value else 0
    if self.active_low:
      output = output * -1 + 1
    GPIO.output(self.pin, output)

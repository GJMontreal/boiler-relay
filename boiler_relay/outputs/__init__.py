from boiler_relay.outputs.actuator import Actuator
from boiler_relay.outputs.gpio_output import GPIOOutput
from boiler_relay.outputs.mqtt_relay import MQTTRelay

def create_output(output_config, mqtt_config):
  if "type" not in output_config:
    raise ValueError(f"output has no type: {output_config}")

  type_name = output_config["type"]
  output_types = {cls.output_type: cls for cls in Actuator.__subclasses__() if cls.output_type}
  if type_name not in output_types:
    raise ValueError(f"unsupported output type: {type_name}")

  return output_types[type_name](output_config, mqtt_config)

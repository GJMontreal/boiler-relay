import logging

from boiler_relay.config import MQTTConfig

log = logging.getLogger(__name__)

class Actuator():
  output_type = None

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    self.output_config = output_config
    self.mqtt_config = mqtt_config

  def start(self):
    pass

  def stop(self):
    pass

  def status(self):
    return None

  def deactivate(self, wait=False):
    self.activate(0)

  # it's up to concrete implementations to do something useful here
  def activate(self, value):
    log.debug("%s.value = %s", self.output_config, value)

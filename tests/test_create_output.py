import pytest

from boiler_relay.config import MQTTConfig
from boiler_relay.outputs import GPIOOutput, MQTTRelay, create_output

MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


def test_builds_the_named_actuator():
  relay = create_output(RELAY, MQTT)

  assert isinstance(relay, MQTTRelay)
  assert relay.mqtt_config is MQTT
  assert relay.relay_config.device == "0xB5EA"
  assert relay.relay_config.topic == "cmnd/x/ZbSend"


def test_builds_a_gpio_output(gpio):
  output = create_output({"type": "gpio", "pin": "P8_10"}, MQTT)

  assert isinstance(output, GPIOOutput)
  assert output.pin == "P8_10"


def test_without_type_raises():
  with pytest.raises(ValueError, match="no type"):
    create_output({"topic": "cmnd/x"}, MQTT)


def test_with_unknown_type_raises():
  with pytest.raises(ValueError, match="Toaster"):
    create_output({"type": "Toaster"}, MQTT)


def test_ignores_names_that_are_not_actuators():
  with pytest.raises(ValueError, match="unsupported"):
    create_output({"type": "Redis"}, MQTT)


def test_a_relay_without_mqtt_config_raises():
  with pytest.raises(ValueError, match="mqtt"):
    create_output(RELAY, None)

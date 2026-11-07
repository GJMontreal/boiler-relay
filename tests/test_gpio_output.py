from boiler_relay.config import MQTTConfig
from boiler_relay.outputs import create_output

MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)


def make_output(active_low=None):
  config = {"type": "gpio", "pin": "P8_10"}
  if active_low is not None:
    config["active_low"] = active_low
  return create_output(config, MQTT)


def test_defaults_to_active_high(gpio):
  assert make_output().active_low is False


def test_starts_inactive(gpio):
  make_output(active_low=True)
  assert gpio == [("P8_10", 1)]

  gpio.clear()
  make_output(active_low=False)
  assert gpio == [("P8_10", 0)]


def test_follows_value(gpio):
  output = make_output()
  gpio.clear()

  output.activate(1)
  output.activate(0)

  assert gpio == [("P8_10", 1), ("P8_10", 0)]


def test_active_low_inverts(gpio):
  output = make_output(active_low=True)
  gpio.clear()

  output.activate(1)
  output.activate(0)

  assert gpio == [("P8_10", 0), ("P8_10", 1)]

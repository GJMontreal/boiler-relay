from json import dumps
from threading import Event
from time import sleep
from types import SimpleNamespace

import pytest

from src import actuator
from src.actuator import GPIOOutput, MQTTRelay, create_output
from src.config import MQTTConfig

MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


def wait_for(condition, timeout=2):
  for _ in range(int(timeout / 0.01)):
    if condition():
      return True
    sleep(0.01)
  return False


@pytest.fixture
def mqtt_clients(monkeypatch):
  class FakeClient:
    instances = []
    gate = None
    entered = Event()
    fail_connect = False

    def __init__(self, version):
      self.version = version
      self.published = []
      FakeClient.instances.append(self)

    def connect(self, host, port, keep_alive):
      if FakeClient.fail_connect:
        raise OSError("unreachable")
      self.address = (host, port, keep_alive)

    def loop_start(self):
      self.looping = True

    def publish(self, topic, payload):
      FakeClient.entered.set()
      if FakeClient.gate is not None:
        FakeClient.gate.wait(2)
      self.published.append((topic, payload))

  monkeypatch.setattr(actuator, "mqtt_client", SimpleNamespace(
    Client=FakeClient,
    CallbackAPIVersion=SimpleNamespace(VERSION2="v2"),
  ))
  return FakeClient


def payload(power):
  return dumps({"Device": "0xB5EA", "Send": {"Power": power}})


def test_create_output_builds_the_named_actuator():
  relay = create_output(RELAY, MQTT)

  assert isinstance(relay, MQTTRelay)
  assert relay.mqtt_config is MQTT
  assert relay.relay_config.device == "0xB5EA"
  assert relay.relay_config.topic == "cmnd/x/ZbSend"


def test_create_output_without_type_returns_none():
  assert create_output({"topic": "cmnd/x"}, MQTT) is None


def test_create_output_with_unknown_type_returns_none():
  assert create_output({"type": "Toaster"}, MQTT) is None


def test_create_output_ignores_names_that_are_not_actuators():
  assert create_output({"type": "Redis"}, MQTT) is None


def test_create_output_builds_a_gpio_output(gpio):
  output = create_output({"type": "gpio", "pin": "P8_10"}, MQTT)

  assert isinstance(output, GPIOOutput)
  assert output.pin == "P8_10"


def test_gpio_output_defaults_to_active_high(gpio):
  assert create_output({"type": "gpio", "pin": "P8_10"}, MQTT).active_low is False


def test_gpio_output_starts_inactive(gpio):
  create_output({"type": "gpio", "pin": "P8_10", "active_low": True}, MQTT)
  assert gpio == [("P8_10", 1)]

  gpio.clear()
  create_output({"type": "gpio", "pin": "P8_10", "active_low": False}, MQTT)
  assert gpio == [("P8_10", 0)]


def test_gpio_output_follows_value(gpio):
  output = create_output({"type": "gpio", "pin": "P8_10"}, MQTT)
  gpio.clear()

  output.activate(1)
  output.activate(0)

  assert gpio == [("P8_10", 1), ("P8_10", 0)]


def test_gpio_output_active_low_inverts(gpio):
  output = create_output({"type": "gpio", "pin": "P8_10", "active_low": True}, MQTT)
  gpio.clear()

  output.activate(1)
  output.activate(0)

  assert gpio == [("P8_10", 0), ("P8_10", 1)]


def test_relay_send_publishes_the_device_message(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  assert mqtt_clients.instances[0].published == [("cmnd/x/ZbSend", payload(1))]


def test_relay_connects_with_the_mqtt_config(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  client = mqtt_clients.instances[0]
  assert client.address == ("broker.local", 1883, 60)
  assert client.looping is True


def test_relay_reuses_its_connection(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)
  relay.send(0)

  assert len(mqtt_clients.instances) == 1
  assert [p for _, p in mqtt_clients.instances[0].published] == [payload(1), payload(0)]


def test_relay_survives_an_unreachable_broker(mqtt_clients, capsys):
  mqtt_clients.fail_connect = True
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  assert "MQTT send failed" in capsys.readouterr().out


def test_relay_without_mqtt_config_reports_and_does_not_raise(capsys):
  relay = create_output(RELAY, None)

  relay.send(1)

  assert "missing MQTT configuration" in capsys.readouterr().out


def test_relay_thread_sends_what_activate_receives(mqtt_clients):
  relay = create_output(RELAY, MQTT)
  relay.start()

  relay.activate(1)

  assert wait_for(lambda: mqtt_clients.instances and mqtt_clients.instances[0].published)
  assert mqtt_clients.instances[0].published == [("cmnd/x/ZbSend", payload(1))]
  relay.stop()
  relay.thread.join(2)
  assert not relay.thread.is_alive()


def test_slow_send_does_not_block_activate_and_keeps_the_latest(mqtt_clients):
  mqtt_clients.gate = Event()
  relay = create_output(RELAY, MQTT)
  relay.start()

  relay.activate(1)
  assert mqtt_clients.entered.wait(2)
  relay.activate(0)
  relay.activate(1)
  relay.activate(0)
  mqtt_clients.gate.set()

  client = mqtt_clients.instances[0]
  assert wait_for(lambda: len(client.published) == 2)
  assert [p for _, p in client.published] == [payload(1), payload(0)]
  relay.stop()

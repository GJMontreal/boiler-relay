import logging
from json import dumps
from threading import Event
from time import sleep
from types import SimpleNamespace

import pytest

from boiler_relay.config import MQTTConfig
from boiler_relay.outputs import create_output, mqtt_relay

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
  class FakeInfo:
    def __init__(self, client):
      self.client = client

    def wait_for_publish(self, timeout=None):
      self.client.waited.append(timeout)

  class FakeClient:
    instances = []
    gate = None
    entered = Event()
    fail_connect = False

    def __init__(self, version):
      self.version = version
      self.published = []
      self.waited = []
      self.looping = False
      self.disconnected = False
      FakeClient.instances.append(self)

    def connect(self, host, port, keep_alive):
      if FakeClient.fail_connect:
        raise OSError("unreachable")
      self.address = (host, port, keep_alive)

    def loop_start(self):
      self.looping = True

    def loop_stop(self):
      self.looping = False

    def disconnect(self):
      self.disconnected = True

    def publish(self, topic, payload):
      FakeClient.entered.set()
      if FakeClient.gate is not None:
        FakeClient.gate.wait(2)
      self.published.append((topic, payload))
      return FakeInfo(self)

  monkeypatch.setattr(mqtt_relay, "mqtt_client", SimpleNamespace(
    Client=FakeClient,
    CallbackAPIVersion=SimpleNamespace(VERSION2="v2"),
  ))
  return FakeClient


def payload(power):
  return dumps({"Device": "0xB5EA", "Send": {"Power": power}})


def test_send_publishes_the_device_message(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  assert mqtt_clients.instances[0].published == [("cmnd/x/ZbSend", payload(1))]


def test_send_does_not_wait_by_default(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  assert mqtt_clients.instances[0].waited == []


def test_connects_with_the_mqtt_config(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)

  client = mqtt_clients.instances[0]
  assert client.address == ("broker.local", 1883, 60)
  assert client.looping is True


def test_reuses_its_connection(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.send(1)
  relay.send(0)

  assert len(mqtt_clients.instances) == 1
  assert [p for _, p in mqtt_clients.instances[0].published] == [payload(1), payload(0)]


def test_an_unreachable_broker_is_warned_about_once(mqtt_clients, caplog):
  mqtt_clients.fail_connect = True
  relay = create_output(RELAY, MQTT)

  with caplog.at_level(logging.INFO, logger="boiler_relay.outputs.mqtt_relay"):
    relay.send(1)
    relay.send(1)
    relay.send(0)

  assert caplog.text.count("MQTT send failed") == 1


def test_a_recovered_broker_is_reported(mqtt_clients, caplog):
  mqtt_clients.fail_connect = True
  relay = create_output(RELAY, MQTT)
  relay.send(1)
  mqtt_clients.fail_connect = False

  with caplog.at_level(logging.INFO, logger="boiler_relay.outputs.mqtt_relay"):
    relay.send(1)

  assert "MQTT send recovered" in caplog.text
  assert mqtt_clients.instances[-1].published == [("cmnd/x/ZbSend", payload(1))]


def test_deactivate_waits_for_the_off_message_to_go_out(mqtt_clients):
  relay = create_output(RELAY, MQTT)

  relay.deactivate(wait=True)

  client = mqtt_clients.instances[0]
  assert client.published == [("cmnd/x/ZbSend", payload(0))]
  assert client.waited == [mqtt_relay.SEND_TIMEOUT]


def test_deactivate_without_waiting_queues_the_off_message(mqtt_clients):
  relay = create_output(RELAY, MQTT)
  relay.start()

  relay.deactivate()

  assert wait_for(lambda: mqtt_clients.instances and mqtt_clients.instances[0].published)
  assert mqtt_clients.instances[0].published == [("cmnd/x/ZbSend", payload(0))]
  relay.stop()


def test_stop_ends_the_thread_and_disconnects(mqtt_clients):
  relay = create_output(RELAY, MQTT)
  relay.start()
  relay.activate(1)
  assert wait_for(lambda: mqtt_clients.instances and mqtt_clients.instances[0].published)

  relay.stop()

  assert not relay.thread.is_alive()
  assert mqtt_clients.instances[0].disconnected is True
  assert mqtt_clients.instances[0].looping is False


def test_stop_without_a_connection_does_not_raise(mqtt_clients):
  create_output(RELAY, MQTT).stop()


def test_thread_sends_what_activate_receives(mqtt_clients):
  relay = create_output(RELAY, MQTT)
  relay.start()

  relay.activate(1)

  assert wait_for(lambda: mqtt_clients.instances and mqtt_clients.instances[0].published)
  assert mqtt_clients.instances[0].published == [("cmnd/x/ZbSend", payload(1))]
  relay.stop()
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

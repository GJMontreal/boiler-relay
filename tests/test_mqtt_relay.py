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
      self.rc = client.rc

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
      self.subscriptions = []
      self.rc = 0
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

    def subscribe(self, topic):
      self.subscriptions.append(topic)

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


class Clock:
  def __init__(self):
    self.value = 0

  def __call__(self):
    return self.value


@pytest.fixture
def clock(monkeypatch):
  fake = Clock()
  monkeypatch.setattr(mqtt_relay, "now", lambda: "2026-11-08T10:00:00Z")
  return fake


def make_relay(clock, config=RELAY):
  relay = create_output(config, MQTT)
  relay.clock = clock
  return relay


def decide(relay, value):
  relay.activate(value)
  if relay.pending.is_set():
    relay.pending.clear()
    relay.send(relay.latest)


def report(relay, power, device="0xB5EA", name="stairwell_heater", extra=None):
  body = {"Device": device, "Name": name, "Power": power, "Endpoint": 1, "LinkQuality": 100}
  body.update(extra or {})
  deliver(relay, dumps({"ZbReceived": {name: body}}))


def deliver(relay, raw):
  relay.on_message(None, None, SimpleNamespace(topic="tele/x/stairwell_heater/SENSOR", payload=raw))


def sent(mqtt_clients):
  return [p for client in mqtt_clients.instances for _, p in client.published]


def test_the_first_decision_sends(mqtt_clients, clock):
  relay = make_relay(clock)

  decide(relay, 0)

  assert sent(mqtt_clients) == [payload(0)]


def test_an_unchanged_state_is_not_sent_again(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  for _ in range(5):
    clock.value += 5
    decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)]


def test_a_changed_state_is_sent(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  decide(relay, 0)

  assert sent(mqtt_clients) == [payload(1), payload(0)]


def test_a_value_that_maps_to_the_same_power_is_not_a_change(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  decide(relay, 1.0)
  decide(relay, True)

  assert sent(mqtt_clients) == [payload(1)]


def test_a_failed_connection_is_resent_on_the_next_decision(mqtt_clients, clock):
  mqtt_clients.fail_connect = True
  relay = make_relay(clock)
  decide(relay, 1)
  mqtt_clients.fail_connect = False

  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)]
  assert relay.failing is False


def test_a_publish_that_returns_an_error_code_is_resent(mqtt_clients, clock, caplog):
  relay = make_relay(clock)
  relay.send(1)
  report(relay, 1)
  mqtt_clients.instances[0].rc = 4

  with caplog.at_level(logging.INFO, logger="boiler_relay.outputs.mqtt_relay"):
    decide(relay, 0)
    decide(relay, 0)
  mqtt_clients.instances[0].rc = 0
  decide(relay, 0)
  decide(relay, 0)

  assert sent(mqtt_clients) == [payload(1), payload(0), payload(0), payload(0)]
  assert caplog.text.count("MQTT send failed") == 1


def test_a_report_that_differs_from_the_command_is_resent(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)
  decide(relay, 1)

  report(relay, 0)
  decide(relay, 1)
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_a_matching_report_confirms_the_command(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  report(relay, 1)

  assert relay.status() == {"confirmed": 1, "confirmed_time": "2026-11-08T10:00:00Z",
                            "confirmed_silent": False}
  assert relay.link_quality == 100
  clock.value += 30
  decide(relay, 1)
  assert sent(mqtt_clients) == [payload(1)]


def test_the_status_is_null_until_the_first_report(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  assert relay.status() == {"confirmed": None, "confirmed_time": None, "confirmed_silent": False}


def test_silence_resends_with_a_growing_delay_up_to_a_cap(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  times = []

  for _ in range(700):
    clock.value += 1
    before = len(sent(mqtt_clients))
    decide(relay, 1)
    if len(sent(mqtt_clients)) > before:
      times.append(clock.value)

  gaps = [b - a for a, b in zip([0] + times, times)]
  assert gaps[:6] == [5, 10, 20, 40, 80, 120]
  assert set(gaps[5:]) == {mqtt_relay.RETRY_CAP}


def test_silence_is_warned_about_once_and_recovery_is_reported(mqtt_clients, clock, caplog):
  relay = make_relay(clock)
  decide(relay, 1)

  with caplog.at_level(logging.INFO, logger="boiler_relay.outputs.mqtt_relay"):
    for _ in range(4):
      clock.value += 60
      decide(relay, 1)
    report(relay, 1)

  assert caplog.text.count("no report from relay") == 1
  assert "is reporting again" in caplog.text


def test_a_report_ends_the_retries(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  clock.value += 6
  decide(relay, 1)
  report(relay, 1)

  clock.value += 30
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_a_new_command_restarts_the_backoff(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  for _ in range(3):
    clock.value += 200
    decide(relay, 1)

  decide(relay, 0)
  clock.value += 4
  decide(relay, 0)
  assert sent(mqtt_clients)[-1] == payload(0)
  count = len(sent(mqtt_clients))
  clock.value += 2
  decide(relay, 0)

  assert len(sent(mqtt_clients)) == count + 1


def test_a_report_for_another_device_is_ignored(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  report(relay, 0, device="0x1234", name="other")
  report(relay, 1, device="0x1234", name="other")

  assert relay.status() == {"confirmed": None, "confirmed_time": None, "confirmed_silent": False}
  clock.value += 6
  decide(relay, 1)
  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_the_device_is_matched_whatever_its_case(mqtt_clients, clock):
  relay = make_relay(clock, {**RELAY, "device": "0xb5ea"})
  decide(relay, 1)

  report(relay, 1, device="0xB5EA")

  assert relay.status()["confirmed"] == 1


@pytest.mark.parametrize("raw", [
  b"",
  b"not json",
  b"\xff\xfe",
  b"[]",
  b"null",
  b'{"ZbReceived": []}',
  b'{"ZbReceived": {"a": 1}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA"}}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA", "Power": 2}}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA", "Power": "1"}}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA", "Power": true}}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA", "Power": null}}}',
  b'{"ZbReceived": {"a": {"Device": "0xB5EA", "LinkQuality": 100}}}',
  b'{"ZbSend": "Done"}',
])
def test_malformed_and_unrelated_payloads_are_ignored(mqtt_clients, clock, raw):
  relay = make_relay(clock)
  decide(relay, 1)

  deliver(relay, raw)

  assert relay.status() == {"confirmed": None, "confirmed_time": None, "confirmed_silent": False}
  clock.value += 6
  decide(relay, 1)
  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_a_report_without_link_quality_still_confirms(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  deliver(relay, dumps({"ZbReceived": {"a": {"Device": "0xB5EA", "Power": 1}}}))

  assert relay.status()["confirmed"] == 1
  assert relay.link_quality is None


def test_the_result_topic_is_not_a_confirmation(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  deliver(relay, dumps({"ZbSend": "Done"}))

  assert relay.status()["confirmed"] is None


def test_a_report_before_any_command_does_not_suppress_the_first_send(mqtt_clients, clock):
  relay = make_relay(clock)

  report(relay, 1)
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)]
  assert relay.status()["confirmed"] == 1


def test_a_restart_sends_the_shutdown_off_and_then_the_first_decision(mqtt_clients, clock):
  first = make_relay(clock)
  decide(first, 1)
  report(first, 1)
  first.deactivate(wait=True)
  second = make_relay(clock)

  decide(second, 0)

  assert sent(mqtt_clients) == [payload(1), payload(0), payload(0)]


def test_a_shutdown_off_is_sent_even_when_the_last_command_was_off(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 0)
  report(relay, 0)

  relay.deactivate(wait=True)

  assert sent(mqtt_clients) == [payload(0), payload(0)]


def test_a_queued_off_is_sent_when_the_last_command_was_on(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  relay.deactivate()
  relay.pending.clear()
  relay.send(relay.latest)

  assert sent(mqtt_clients) == [payload(1), payload(0)]


def test_the_report_topic_comes_from_the_command_topic(mqtt_clients, clock):
  relay = make_relay(clock, {**RELAY, "topic": "cmnd/tasmota_E3738F/ZbSend"})
  relay.send(1)

  relay.on_connect(mqtt_clients.instances[0], None, None, 0, None)

  assert mqtt_clients.instances[0].subscriptions == ["tele/tasmota_E3738F/+/SENSOR"]


def test_the_relay_subscribes_again_on_every_connect(mqtt_clients, clock):
  relay = make_relay(clock)
  relay.send(1)
  client = mqtt_clients.instances[0]

  relay.on_connect(client, None, None, 0, None)
  relay.on_connect(client, None, None, 0, None)

  assert client.subscriptions == ["tele/x/+/SENSOR"] * 2


def test_the_client_is_wired_to_the_callbacks(mqtt_clients, clock):
  relay = make_relay(clock)

  relay.send(1)

  client = mqtt_clients.instances[0]
  assert client.on_connect == relay.on_connect
  assert client.on_message == relay.on_message


def test_a_refused_connection_does_not_subscribe(mqtt_clients, clock):
  relay = make_relay(clock)
  relay.send(1)
  refused = SimpleNamespace(is_failure=True)

  relay.on_connect(mqtt_clients.instances[0], None, None, refused, None)

  assert mqtt_clients.instances[0].subscriptions == []


def test_a_topic_without_a_report_topic_sends_on_change_and_never_retries(mqtt_clients, clock):
  relay = make_relay(clock, {**RELAY, "topic": "relay/set"})
  decide(relay, 1)

  relay.on_connect(mqtt_clients.instances[0], None, None, 0, None)
  clock.value += 30
  decide(relay, 1)
  decide(relay, 0)

  assert mqtt_clients.instances[0].subscriptions == []
  assert sent(mqtt_clients) == [payload(1), payload(0)]


def test_a_noisy_relay_is_sent_at_most_once_per_decision(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  for _ in range(10):
    report(relay, 0)

  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_a_matched_state_sends_nothing_before_the_refresh_interval(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  for _ in range(mqtt_relay.REFRESH_INTERVAL // 5 - 1):
    clock.value += 5
    decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)]


def test_a_matched_state_is_sent_once_at_the_refresh_interval(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  clock.value += mqtt_relay.REFRESH_INTERVAL
  decide(relay, 1)
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1), payload(1)]


def test_a_confirmed_refresh_schedules_the_next_one_an_interval_later(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)
  clock.value += mqtt_relay.REFRESH_INTERVAL
  decide(relay, 1)
  report(relay, 1)

  clock.value += mqtt_relay.REFRESH_INTERVAL - 1
  decide(relay, 1)
  clock.value += 1
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)] * 3


def test_a_refresh_goes_through_the_report_check_and_the_backoff(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)
  clock.value += mqtt_relay.REFRESH_INTERVAL
  decide(relay, 1)
  assert len(sent(mqtt_clients)) == 2

  clock.value += mqtt_relay.CONFIRM_TIMEOUT - 1
  decide(relay, 1)
  assert len(sent(mqtt_clients)) == 2
  clock.value += 1
  decide(relay, 1)
  assert len(sent(mqtt_clients)) == 3
  clock.value += mqtt_relay.CONFIRM_TIMEOUT
  decide(relay, 1)
  assert len(sent(mqtt_clients)) == 3
  clock.value += mqtt_relay.CONFIRM_TIMEOUT
  decide(relay, 1)
  assert len(sent(mqtt_clients)) == 4


def test_a_refresh_answered_by_a_different_state_corrects_the_relay(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 0)
  report(relay, 0)
  clock.value += mqtt_relay.REFRESH_INTERVAL
  decide(relay, 0)

  report(relay, 1)
  decide(relay, 0)

  assert sent(mqtt_clients) == [payload(0)] * 3


def test_a_failed_refresh_is_resent_on_the_next_tick(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)
  clock.value += mqtt_relay.REFRESH_INTERVAL
  mqtt_clients.instances[0].rc = 4
  decide(relay, 1)
  mqtt_clients.instances[0].rc = 0

  clock.value += 1
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)] * 3
  assert relay.failing is False


def test_the_refresh_applies_without_a_report_topic(mqtt_clients, clock):
  relay = make_relay(clock, {**RELAY, "topic": "relay/set"})
  decide(relay, 1)

  clock.value += mqtt_relay.REFRESH_INTERVAL - 1
  decide(relay, 1)
  clock.value += 1
  decide(relay, 1)

  assert sent(mqtt_clients) == [payload(1)] * 2
  assert relay.status()["confirmed_silent"] is False


def test_confirmed_silent_is_false_before_any_command(mqtt_clients, clock):
  relay = make_relay(clock)

  clock.value += 1000

  assert relay.status()["confirmed_silent"] is False


def test_confirmed_silent_turns_true_after_the_first_backoff_step(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)

  clock.value += mqtt_relay.CONFIRM_TIMEOUT - 1
  assert relay.status()["confirmed_silent"] is False
  clock.value += 1
  assert relay.status()["confirmed_silent"] is True


def test_confirmed_silent_stays_true_across_resends(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  states = []

  for _ in range(60):
    clock.value += 1
    decide(relay, 1)
    states.append(relay.status()["confirmed_silent"])

  assert states[mqtt_relay.CONFIRM_TIMEOUT - 1:] == [True] * (60 - mqtt_relay.CONFIRM_TIMEOUT + 1)


def test_a_matching_report_clears_confirmed_silent(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  clock.value += 30
  assert relay.status()["confirmed_silent"] is True

  report(relay, 1)

  assert relay.status()["confirmed_silent"] is False


def test_a_mismatching_report_does_not_clear_confirmed_silent(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  clock.value += 30

  report(relay, 0)

  assert relay.status()["confirmed_silent"] is True


def test_a_new_command_starts_a_new_unconfirmed_period(mqtt_clients, clock):
  relay = make_relay(clock)
  decide(relay, 1)
  report(relay, 1)

  decide(relay, 0)
  clock.value += mqtt_relay.CONFIRM_TIMEOUT - 1
  assert relay.status()["confirmed_silent"] is False
  clock.value += 1

  assert relay.status()["confirmed_silent"] is True

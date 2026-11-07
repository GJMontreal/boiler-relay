import json
import logging
from datetime import datetime, timedelta, timezone
from threading import Thread

import pytest

from boiler_relay import zone as zone_module
from boiler_relay.config import MQTTConfig, RedisConfig, ZoneConfig
from boiler_relay.outputs import GPIOOutput, MQTTRelay
from boiler_relay.zone import Zone

SENSOR = "/home/sensors/a"
STATE = f"{SENSOR}/heating_cooling_state"
CONTROL = f"{SENSOR}/control_value"
REDIS = RedisConfig(host="redis.local", port=6380)
MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
VALVE = {"type": "gpio", "pin": "P8_10"}
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


class FixedPID:
  def __init__(self, value):
    self.value = value
    self.setpoint = None
    self.components = (0, 0, 0)
    self.resets = 0

  def __call__(self, current):
    return self.value

  def reset(self):
    self.resets += 1


class RecordingOutput:
  def __init__(self):
    self.values = []
    self.deactivations = []
    self.stopped = False

  def activate(self, value):
    self.values.append(value)

  def deactivate(self, wait=False):
    self.deactivations.append(wait)

  def stop(self):
    self.stopped = True


def timestamp(age=0):
  moment = datetime.now(timezone.utc) - timedelta(seconds=age)
  return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_zone(outputs=(), active_low=False, mqtt=MQTT, **changes):
  config = ZoneConfig(
    sensor_path=SENSOR,
    name="Bedrooms",
    outputs=list(outputs),
    pid_interval="10",
    active_low=active_low,
    **changes,
  )
  return Zone(config, REDIS, mqtt)


def make_fixed_zone(value, outputs=(), **changes):
  zone = make_zone(outputs, **changes)
  zone.pid = FixedPID(value)
  return zone


def seed(redis_client, current=None, target=None, state=None, age=0, sample_time=None):
  if current is not None:
    reading = {"value": current, "time": sample_time or timestamp(age)}
    redis_client.set(f"{SENSOR}/current_temperature", json.dumps(reading))
  if target is not None:
    redis_client.set(f"{SENSOR}/target_temperature", json.dumps({"value": target}))
  if state is not None:
    redis_client.set(f"{SENSOR}/target_heatingcooling_state", state)


def published_states(redis_client, run_ticks, zone, ticks):
  states = []
  run_ticks(zone, ticks, on_tick=lambda: states.append(int(redis_client.get(STATE))))
  return states


def test_zone_is_named_and_reads_its_sensor(redis_client, gpio):
  zone = make_zone()

  assert zone.name == "Bedrooms"
  assert zone.input_path == SENSOR
  assert zone.output_path == CONTROL


def test_zone_opens_one_redis_connection_from_the_config(redis_client, redis_connections, gpio):
  make_zone([VALVE])

  assert redis_connections == [{"host": "redis.local", "port": 6380, "db": 0}]


def test_zone_builds_an_output_for_each_config_entry(redis_client, gpio):
  zone = make_zone([VALVE, {"type": "gpio", "pin": "P8_14"}])

  assert [type(output) for output in zone.outputs] == [GPIOOutput, GPIOOutput]
  assert [output.pin for output in zone.outputs] == ["P8_10", "P8_14"]


def test_zone_builds_a_relay_with_the_mqtt_config(redis_client):
  zone = make_zone([RELAY])

  assert isinstance(zone.outputs[0], MQTTRelay)
  assert zone.outputs[0].mqtt_config is MQTT


@pytest.mark.parametrize("active_low", [True, False])
def test_gpio_outputs_inherit_zone_active_low(redis_client, gpio, active_low):
  zone = make_zone([VALVE], active_low=active_low)

  assert zone.outputs[0].active_low is active_low


def test_zone_rejects_an_unsupported_output_type(redis_client, gpio):
  with pytest.raises(ValueError, match="Toaster"):
    make_zone([{"type": "Toaster"}])


def test_zone_rejects_a_relay_without_mqtt_config(redis_client):
  with pytest.raises(ValueError, match="mqtt"):
    make_zone([RELAY], mqtt=None)


def test_zone_without_outputs_has_none(redis_client, gpio):
  assert make_zone().outputs == []


def test_pid_gains_come_from_the_zone_config(redis_client, gpio):
  zone = make_zone(pid={"kp": 2, "ki": 0.5, "kd": 0.25})

  assert zone.pid.tunings == (2, 0.5, 0.25)


def test_duty_window_comes_from_control_interval(redis_client, gpio):
  assert make_zone().duration == 10 * 60 / 5
  assert make_zone(control_interval=5).duration == 5 * 60 / 5


def test_start_starts_outputs_then_the_zone_thread(redis_client, gpio, monkeypatch):
  zone = make_zone()
  started = []
  zone.outputs = [RecordingOutput()]
  monkeypatch.setattr(zone.outputs[0], "start", lambda: started.append("output"), raising=False)
  monkeypatch.setattr(Thread, "start", lambda self: started.append("zone"))

  zone.start()

  assert started == ["output", "zone"]


def test_cold_room_calls_for_heat(redis_client, gpio, run_ticks):
  seed(redis_client, current=15, target=21)
  zone = make_zone()
  zone.pid.sample_time = 0

  run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) > 0


def test_warm_room_calls_for_nothing(redis_client, gpio, run_ticks):
  seed(redis_client, current=25, target=21)
  zone = make_zone()
  zone.pid.sample_time = 0

  run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) == 0


def test_control_value_is_limited_to_unit_range(redis_client, gpio, run_ticks):
  seed(redis_client, current=-40, target=40)
  zone = make_zone()
  zone.pid.sample_time = 0

  run_ticks(zone, 3)

  assert 0 <= float(redis_client.get(CONTROL)) <= 1


def test_records_sample_time(redis_client, gpio, run_ticks):
  reported = timestamp()
  seed(redis_client, current=18, target=21, sample_time=reported)
  zone = make_zone()

  run_ticks(zone, 1)

  assert zone.last_sample_time == reported


def test_missing_temperature_calls_for_nothing(redis_client, gpio, run_ticks):
  seed(redis_client, target=21, state=1)
  zone = make_zone()

  run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) == 0
  assert redis_client.get(STATE) == b"0"


def test_a_stale_reading_at_startup_calls_for_nothing(redis_client, gpio, run_ticks, caplog):
  seed(redis_client, current=14.6, target=21, state=1, age=14 * 24 * 3600)
  zone = make_zone()
  zone.pid.sample_time = 0

  with caplog.at_level(logging.WARNING, logger="boiler_relay.zone"):
    run_ticks(zone, 2)

  assert float(redis_client.get(CONTROL)) == 0
  assert redis_client.get(STATE) == b"0"
  assert [r.getMessage() for r in caplog.records].count("zone Bedrooms: temperature reading is stale since "
    + zone.last_sample_time + ", calling for no heat") == 1


def test_a_reading_inside_the_limit_is_used(redis_client, gpio, run_ticks):
  seed(redis_client, current=15, target=21, age=3600)
  zone = make_zone()
  zone.pid.sample_time = 0

  run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) > 0


def test_a_reading_that_stops_changing_goes_stale(redis_client, gpio, run_ticks, monkeypatch):
  clock = [1000.0]
  monkeypatch.setattr(zone_module, "monotonic", lambda: clock[0])
  seed(redis_client, current=15, target=21)
  zone = make_zone()
  zone.pid.sample_time = 0

  run_ticks(zone, 1)
  assert float(redis_client.get(CONTROL)) > 0

  clock[0] += zone_module.STALE_AFTER + 1
  run_ticks(zone, 1)
  assert float(redis_client.get(CONTROL)) == 0


def test_a_new_sample_time_makes_the_reading_fresh_again(redis_client, gpio, run_ticks, monkeypatch):
  clock = [1000.0]
  monkeypatch.setattr(zone_module, "monotonic", lambda: clock[0])
  seed(redis_client, current=15, target=21)
  zone = make_zone()
  zone.pid.sample_time = 0
  run_ticks(zone, 1)

  clock[0] += zone_module.STALE_AFTER + 1
  run_ticks(zone, 1)
  assert float(redis_client.get(CONTROL)) == 0

  seed(redis_client, current=15, target=21, sample_time="2099-01-01T00:00:00Z")
  run_ticks(zone, 1)
  assert float(redis_client.get(CONTROL)) > 0


def test_going_stale_resets_the_pid(redis_client, gpio, run_ticks):
  seed(redis_client, current=15, target=21, age=3 * 3600)
  zone = make_fixed_zone(1)

  run_ticks(zone, 3)

  assert zone.pid.resets == 1


def test_an_unreadable_sample_time_is_treated_as_fresh(redis_client, gpio, run_ticks, caplog):
  seed(redis_client, current=15, target=21, sample_time="t0")
  zone = make_zone()
  zone.pid.sample_time = 0

  with caplog.at_level(logging.WARNING, logger="boiler_relay.zone"):
    run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) > 0
  assert "cannot read the sample time" in caplog.text


@pytest.mark.parametrize("value", ["2", "3", "9", "junk"])
def test_unsupported_target_states_are_off_and_warned_once(redis_client, gpio, run_ticks, caplog, value):
  seed(redis_client, current=20, target=21, state=value)
  zone = make_fixed_zone(1)
  output = RecordingOutput()
  zone.outputs = [output]

  with caplog.at_level(logging.WARNING, logger="boiler_relay.zone"):
    run_ticks(zone, 3)

  assert output.values == [0, 0, 0]
  assert redis_client.get(STATE) == b"0"
  assert caplog.text.count("unsupported target state") == 1


def test_a_supported_state_clears_the_warning(redis_client, gpio, run_ticks, caplog):
  seed(redis_client, current=20, target=21, state=2)
  zone = make_fixed_zone(1)

  with caplog.at_level(logging.INFO, logger="boiler_relay.zone"):
    run_ticks(zone, 1)
    seed(redis_client, state=1)
    run_ticks(zone, 1)

  assert "target state is back to normal" in caplog.text


def test_duty_cycle_matches_control_value(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(0.25)

  states = published_states(redis_client, run_ticks, zone, 120)

  on_ticks = int(0.25 * zone.duration)
  assert states == [1] * on_ticks + [0] * (120 - on_ticks)


def test_cycle_wraps_after_full_duration(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(0.1)

  states = published_states(redis_client, run_ticks, zone, 121)

  assert states[0] == 1
  assert states[120] == 1


def test_off_state_never_opens_valve(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=0)
  zone = make_fixed_zone(1)

  states = published_states(redis_client, run_ticks, zone, 5)

  assert set(states) == {0}


def test_waits_without_target_state(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21)
  output = RecordingOutput()
  zone = make_fixed_zone(1)
  zone.outputs = [output]

  run_ticks(zone, 3)

  assert redis_client.get(STATE) is None
  assert output.values == []
  assert redis_client.get(CONTROL) == b"1"


def test_publishes_state(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)

  run_ticks(zone, 1)

  assert redis_client.get(STATE) == b"1"


def test_boost_forces_valve_open(redis_client, gpio, run_ticks):
  seed(redis_client, current=22, target=21, state=0)
  redis_client.set(f"{SENSOR}/boost", "true")
  zone = make_fixed_zone(0)

  run_ticks(zone, 1)

  assert redis_client.get(STATE) == b"1"


def test_every_output_follows_the_state_each_tick(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  first, second = RecordingOutput(), RecordingOutput()
  zone = make_fixed_zone(1)
  zone.outputs = [first, second]

  run_ticks(zone, 3)

  assert first.values == [1, 1, 1]
  assert second.values == [1, 1, 1]


def test_gpio_output_is_driven_by_the_zone(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_zone([VALVE], active_low=True)
  zone.pid = FixedPID(1)

  run_ticks(zone, 1)

  assert gpio == [("P8_10", 1), ("P8_10", 0)]


def test_state_changes_are_logged_once(redis_client, gpio, run_ticks, caplog):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)

  with caplog.at_level(logging.INFO, logger="boiler_relay.zone"):
    run_ticks(zone, 4)

  assert caplog.text.count("zone Bedrooms None -> HeatingCoolingState.HEAT") == 1


def test_a_window_summary_is_logged_when_the_cycle_wraps(redis_client, gpio, run_ticks, caplog):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(0.5, control_interval=0.5)

  with caplog.at_level(logging.INFO, logger="boiler_relay.zone"):
    run_ticks(zone, 6)

  assert "zone Bedrooms window control_mean=0.500 on_fraction=0.500 ticks=6" in caplog.text


def test_a_failed_tick_does_not_stop_the_loop(redis_client, gpio, run_ticks, monkeypatch):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)
  output = RecordingOutput()
  zone.outputs = [output]
  calls = {"count": 0}
  real_get = zone.redis.get

  def flaky_get(key):
    calls["count"] += 1
    if calls["count"] <= 2:
      raise ConnectionError("redis is down")
    return real_get(key)

  monkeypatch.setattr(zone.redis, "get", flaky_get)

  run_ticks(zone, 4)

  assert output.values != []
  assert output.deactivations == []


def test_three_failed_ticks_in_a_row_drive_outputs_inactive(redis_client, gpio, run_ticks, monkeypatch, caplog):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)
  output = RecordingOutput()
  zone.outputs = [output]

  def broken_get(key):
    raise ConnectionError("redis is down")

  monkeypatch.setattr(zone.redis, "get", broken_get)

  with caplog.at_level(logging.ERROR, logger="boiler_relay.zone"):
    run_ticks(zone, 3)

  assert output.values == []
  assert output.deactivations == [False]
  assert "redis is down" in caplog.text


def test_the_zone_resumes_when_ticks_succeed_again(redis_client, gpio, run_ticks, monkeypatch, caplog):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)
  output = RecordingOutput()
  zone.outputs = [output]
  real_get = zone.redis.get
  broken = {"on": True}

  def get(key):
    if broken["on"]:
      raise ConnectionError("redis is down")
    return real_get(key)

  monkeypatch.setattr(zone.redis, "get", get)
  run_ticks(zone, 3)
  broken["on"] = False

  with caplog.at_level(logging.INFO, logger="boiler_relay.zone"):
    run_ticks(zone, 2)

  assert output.values == [1, 1]
  assert "recovered after 3 failed ticks" in caplog.text


def test_an_output_that_raises_counts_as_a_failure(redis_client, gpio, run_ticks):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)
  output = RecordingOutput()

  def activate(value):
    raise OSError("pin failed")

  output.activate = activate
  zone.outputs = [output]

  run_ticks(zone, 3)

  assert output.deactivations == [False]


def test_an_output_that_cannot_be_deactivated_does_not_raise(redis_client, gpio, caplog):
  zone = make_zone()
  output = RecordingOutput()

  def deactivate(wait=False):
    raise OSError("pin failed")

  output.deactivate = deactivate
  zone.outputs = [output, RecordingOutput()]

  with caplog.at_level(logging.ERROR, logger="boiler_relay.zone"):
    zone.deactivate_outputs()

  assert "could not drive an output inactive" in caplog.text
  assert zone.outputs[1].deactivations == [False]


def test_shutdown_drives_outputs_inactive_and_stops_them(redis_client, gpio):
  zone = make_zone()
  output = RecordingOutput()
  zone.outputs = [output]

  zone.shutdown()

  assert zone.stopping.is_set()
  assert output.deactivations == [True]
  assert output.stopped is True


def test_the_loop_exits_when_stopping_is_set(redis_client, gpio, monkeypatch):
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)
  monkeypatch.setattr(zone_module, "sleep", lambda _: zone.stopping.set())

  zone.run()

  assert zone.stopping.is_set()


def make_shadow_zone(value, outputs=(VALVE,), **changes):
  config = ZoneConfig(sensor_path=SENSOR, name="Bedrooms", outputs=list(outputs), pid_interval="10", **changes)
  zone = Zone(config, REDIS, MQTT, mode="shadow")
  zone.pid = FixedPID(value)
  return zone


def test_a_shadow_zone_builds_no_outputs_and_touches_no_gpio(redis_client, gpio):
  zone = make_shadow_zone(1.0, [VALVE, {"type": "gpio", "pin": "P8_14"}])

  assert zone.outputs == []
  assert gpio == []


def test_a_shadow_zone_builds_no_mqtt_relay(redis_client, gpio):
  assert make_shadow_zone(1.0, [RELAY]).outputs == []


def test_a_shadow_zone_writes_only_under_the_shadow_prefix(redis_client, gpio, run_ticks):
  seed(redis_client, current=18, target=21, state=1)
  before = set(redis_client.keys())
  zone = make_shadow_zone(1.0)

  run_ticks(zone, 3)

  written = set(redis_client.keys()) - before
  assert written == {b"boiler_relay/shadow/zones/Bedrooms"}
  assert gpio == []
  data = json.loads(redis_client.get("boiler_relay/shadow/zones/Bedrooms"))
  assert data["state"] == 1
  assert data["control_value"] == 1.0


def test_a_shadow_zone_publishes_nothing_on_the_homebridge_channel(redis_client, gpio, run_ticks):
  seed(redis_client, current=18, target=21, state=1)
  channel = redis_client.pubsub()
  channel.subscribe(STATE)
  channel.get_message()

  run_ticks(make_shadow_zone(1.0), 2)

  assert channel.get_message() is None


def test_a_shadow_zone_publishes_a_null_state_before_the_target_state_exists(redis_client, gpio, run_ticks):
  seed(redis_client, current=18, target=21)

  run_ticks(make_shadow_zone(1.0), 1)

  data = json.loads(redis_client.get("boiler_relay/shadow/zones/Bedrooms"))
  assert data["state"] is None


def test_an_active_zone_also_publishes_under_the_active_prefix(redis_client, gpio, run_ticks):
  seed(redis_client, current=18, target=21, state=1)
  zone = make_fixed_zone(1.0, [VALVE])

  run_ticks(zone, 2)

  data = json.loads(redis_client.get("boiler_relay/active/zones/Bedrooms"))
  assert data["state"] == 1
  assert redis_client.get(STATE) is not None


def test_a_zone_knows_whether_it_has_an_end_switch(redis_client, gpio):
  assert make_shadow_zone(0.0, [{**VALVE, "end_switch": "P8_9"}]).has_end_switch
  assert not make_shadow_zone(0.0, [VALVE]).has_end_switch

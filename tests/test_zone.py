import json
from threading import Thread

import pytest

from src import zone as zone_module
from src.actuator import GPIOOutput, MQTTRelay
from src.config import MQTTConfig, RedisConfig, ZoneConfig
from src.zone import Zone

SENSOR = "/home/sensors/a"
STATE = f"{SENSOR}/heating_cooling_state"
CONTROL = f"{SENSOR}/control_value"
REDIS = RedisConfig(host="redis.local", port=6380)
MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


class FixedPID:
  def __init__(self, value):
    self.value = value
    self.setpoint = None
    self.components = (0, 0, 0)

  def __call__(self, current):
    return self.value


class RecordingOutput:
  def __init__(self):
    self.values = []

  def activate(self, value):
    self.values.append(value)


def make_zone(outputs=(), active_low=False):
  config = ZoneConfig(
    sensor_path=SENSOR,
    name="Bedrooms",
    outputs=list(outputs),
    pid_interval="10",
    control_interval="10",
    active_low=active_low,
  )
  return Zone(config, REDIS, MQTT)


def make_fixed_zone(value, outputs=()):
  zone = make_zone(outputs)
  zone.pid = FixedPID(value)
  return zone


def seed(redis_client, current=None, target=None, state=None):
  if current is not None:
    redis_client.set(f"{SENSOR}/current_temperature", json.dumps({"value": current, "time": "t0"}))
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
  make_zone([{"type": "gpio", "pin": "P8_10"}, RELAY])

  assert redis_connections == [{"host": "redis.local", "port": 6380, "db": 0}]


def test_zone_builds_an_output_for_each_config_entry(redis_client, gpio):
  zone = make_zone([
    {"type": "gpio", "pin": "P8_10"},
    RELAY,
    {"type": "gpio", "pin": "P8_14"},
  ])

  assert [type(output) for output in zone.outputs] == [GPIOOutput, MQTTRelay, GPIOOutput]
  assert [o.pin for o in zone.outputs if isinstance(o, GPIOOutput)] == ["P8_10", "P8_14"]
  assert zone.outputs[1].mqtt_config is MQTT


@pytest.mark.parametrize("active_low", [True, False])
def test_gpio_outputs_inherit_zone_active_low(redis_client, gpio, active_low):
  zone = make_zone([{"type": "gpio", "pin": "P8_10"}], active_low=active_low)

  assert zone.outputs[0].active_low is active_low


def test_output_active_low_overrides_the_zone(redis_client, gpio):
  zone = make_zone([{"type": "gpio", "pin": "P8_10", "active_low": False}], active_low=True)

  assert zone.outputs[0].active_low is False


def test_zone_skips_outputs_of_unknown_type(redis_client, gpio):
  zone = make_zone([{"type": "Toaster"}, RELAY])

  assert len(zone.outputs) == 1


def test_zone_without_outputs_has_none(redis_client, gpio):
  assert make_zone().outputs == []


def test_start_starts_outputs_then_the_zone_thread(redis_client, gpio, monkeypatch):
  zone = make_zone([RELAY])
  started = []
  monkeypatch.setattr(zone.outputs[0], "start", lambda: started.append("relay"))
  monkeypatch.setattr(Thread, "start", lambda self: started.append("zone"))

  zone.start()

  assert started == ["relay", "zone"]


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
  seed(redis_client, current=18, target=21)
  zone = make_zone()

  run_ticks(zone, 1)

  assert zone.last_sample_time == "t0"


def test_missing_temperature_calls_for_nothing(redis_client, gpio, run_ticks):
  seed(redis_client, target=21, state=1)
  zone = make_zone()

  run_ticks(zone, 1)

  assert float(redis_client.get(CONTROL)) == 0
  assert redis_client.get(STATE) == b"0"


def test_duration_is_ten_minutes_of_ticks(redis_client, gpio):
  zone = make_zone()

  assert zone.duration == 10 * 60 / zone.interval


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
  zone = make_zone([{"type": "gpio", "pin": "P8_10"}], active_low=True)
  zone.pid = FixedPID(1)

  run_ticks(zone, 1)

  assert gpio == [("P8_10", 1), ("P8_10", 0)]


def test_write_row_to_csv_appends_to_zone_log(redis_client, gpio, tmp_path, monkeypatch):
  monkeypatch.setattr(zone_module, "LOG_PATH", str(tmp_path))
  zone = make_zone()

  zone.write_row_to_csv(["t0", "18.0"])
  zone.write_row_to_csv(["t1", "18.5"])

  assert (tmp_path / "Bedrooms_pid.csv").read_text().splitlines() == ["t0,18.0", "t1,18.5"]


def test_write_row_formats_the_sample(redis_client, gpio, tmp_path, monkeypatch):
  monkeypatch.setattr(zone_module, "LOG_PATH", str(tmp_path))
  zone = make_zone()
  zone.last_sample_time = "t0"
  zone.current_temperature = 18.04
  zone.target_temperature = 21
  zone.control_value = 0.5

  zone.write_row()

  row = (tmp_path / "Bedrooms_pid.csv").read_text().strip().split(",")
  assert row[:4] == ["t0", "18.0", "21.0", "60"]
  assert len(row) == 7


def test_each_tick_logs_a_row_when_the_log_directory_exists(redis_client, gpio, tmp_path, monkeypatch, run_ticks):
  monkeypatch.setattr(zone_module, "LOG_PATH", str(tmp_path))
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)

  run_ticks(zone, 2)

  assert len((tmp_path / "Bedrooms_pid.csv").read_text().splitlines()) == 2


def test_no_log_is_written_when_the_directory_is_missing(redis_client, gpio, tmp_path, monkeypatch, run_ticks):
  monkeypatch.setattr(zone_module, "LOG_PATH", str(tmp_path / "missing"))
  seed(redis_client, current=20, target=21, state=1)
  zone = make_fixed_zone(1)

  run_ticks(zone, 2)

  assert not (tmp_path / "missing").exists()

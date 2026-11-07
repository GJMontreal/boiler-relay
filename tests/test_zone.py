import pytest

from src.actuator import GPIOOutput, MQTTRelay
from src.config import MQTTConfig, RedisConfig, ZoneConfig
from src.zone import Zone

REDIS = RedisConfig(host="redis.local", port=6380)
MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


def make_zone(outputs=(), active_low=False):
  config = ZoneConfig(
    sensor_path="/home/sensors/a",
    name="Bedrooms",
    outputs=list(outputs),
    pid_interval="10",
    control_interval="10",
    active_low=active_low,
  )
  return Zone(config, REDIS, MQTT)


def test_zone_reads_sensor_and_writes_control_value(redis_client, gpio):
  zone = make_zone()

  assert zone.name == "Bedrooms"
  assert zone.input_path == "/home/sensors/a"
  assert zone.output_path == "/home/sensors/a/control_value"
  assert zone.pid_thread.pid_interval == 10.0


def test_zone_builds_an_actuator_for_each_output(redis_client, gpio):
  zone = make_zone([
    {"type": "gpio", "pin": "P8_10"},
    RELAY,
    {"type": "gpio", "pin": "P8_14"},
  ])

  assert [type(actuator) for actuator in zone.actuators] == [GPIOOutput, MQTTRelay, GPIOOutput]
  assert [actuator.pin for actuator in zone.actuators if isinstance(actuator, GPIOOutput)] == ["P8_10", "P8_14"]
  assert all(actuator.path == "/home/sensors/a" for actuator in zone.actuators)
  assert zone.actuators[1].mqtt_config is MQTT


@pytest.mark.parametrize("active_low", [True, False])
def test_gpio_outputs_inherit_zone_active_low(redis_client, gpio, active_low):
  zone = make_zone([{"type": "gpio", "pin": "P8_10"}], active_low=active_low)

  assert zone.actuators[0].active_low is active_low


def test_output_active_low_overrides_the_zone(redis_client, gpio):
  zone = make_zone([{"type": "gpio", "pin": "P8_10", "active_low": False}], active_low=True)

  assert zone.actuators[0].active_low is False


def test_valve_thread_reads_the_zone_sensor(redis_client, gpio):
  zone = make_zone()

  assert zone.zone_valve_thread.sensor_path == "/home/sensors/a"
  assert zone.zone_valve_thread.zone is zone


def test_start_starts_both_threads(redis_client, gpio, monkeypatch):
  zone = make_zone()
  started = []
  monkeypatch.setattr(zone.pid_thread, "start", lambda: started.append("pid"))
  monkeypatch.setattr(zone.zone_valve_thread, "start", lambda: started.append("valve"))

  zone.start()

  assert started == ["pid", "valve"]


def test_write_row_to_csv_appends_to_zone_log(redis_client, gpio, tmp_path, monkeypatch):
  monkeypatch.setattr("src.zone.LOG_PATH", str(tmp_path))
  zone = make_zone()

  zone.write_row_to_csv(["t0", "18.0"])
  zone.write_row_to_csv(["t1", "18.5"])

  assert (tmp_path / "Bedrooms_pid.csv").read_text().splitlines() == ["t0,18.0", "t1,18.5"]


def test_write_row_formats_the_sample(redis_client, gpio, tmp_path, monkeypatch):
  monkeypatch.setattr("src.zone.LOG_PATH", str(tmp_path))
  zone = make_zone()
  zone.last_sample_time = "t0"
  zone.current_temperature = 18.04
  zone.target_temperature = 21
  zone.control_value = 0.5

  zone.write_row()

  row = (tmp_path / "Bedrooms_pid.csv").read_text().strip().split(",")
  assert row[:4] == ["t0", "18.0", "21.0", "60"]
  assert len(row) == 7


def test_threads_connect_with_the_redis_config(redis_client, redis_connections, gpio):
  make_zone()

  assert redis_connections == [{"host": "redis.local", "port": 6380, "db": 0}] * 2


def test_zone_skips_outputs_of_unknown_type(redis_client, gpio):
  zone = make_zone([{"type": "Toaster"}, RELAY])

  assert len(zone.actuators) == 1


def test_zone_without_outputs_has_no_actuators(redis_client, gpio):
  assert make_zone().actuators == []


def test_start_starts_the_actuators(redis_client, gpio, monkeypatch):
  zone = make_zone([RELAY])
  started = []
  monkeypatch.setattr(zone.pid_thread, "start", lambda: None)
  monkeypatch.setattr(zone.zone_valve_thread, "start", lambda: None)
  monkeypatch.setattr(zone.actuators[0], "start", lambda: started.append("relay"))

  zone.start()

  assert started == ["relay"]

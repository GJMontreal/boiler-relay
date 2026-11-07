import pytest

from src.config import RedisConfig, ZoneConfig
from src.zone import Zone

REDIS = RedisConfig(host="localhost", port=6379)


def make_zone(outputs=(), active_low=False):
  config = ZoneConfig(
    sensor_path="/home/sensors/a",
    name="Bedrooms",
    outputs=list(outputs),
    pid_interval="10",
    control_interval="10",
    active_low=active_low,
  )
  return Zone(config, REDIS)


def test_zone_reads_sensor_and_writes_control_value(redis_client, gpio):
  zone = make_zone()

  assert zone.name == "Bedrooms"
  assert zone.input_path == "/home/sensors/a"
  assert zone.output_path == "/home/sensors/a/control_value"
  assert zone.pid_thread.pid_interval == 10.0


def test_valve_thread_drives_only_gpio_outputs(redis_client, gpio):
  zone = make_zone([
    {"type": "gpio", "pin": "P8_10"},
    {"type": "MQTTRelay", "topic": "cmnd/x", "device": "0xB5EA"},
    {"type": "gpio", "pin": "P8_14"},
  ])

  assert zone.zone_valve_thread.output_gpio == ["P8_10", "P8_14"]


@pytest.mark.parametrize("active_low", [True, False])
def test_valve_thread_inherits_active_low(redis_client, gpio, active_low):
  zone = make_zone(active_low=active_low)

  assert zone.zone_valve_thread.active_low is active_low


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

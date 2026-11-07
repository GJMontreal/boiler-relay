from json import dumps, load as json_load

import pytest

from src.config import MQTTConfig, RedisConfig, ZoneConfig


def test_from_file_builds_dataclass(tmp_path):
  path = tmp_path / "redis.json"
  path.write_text(dumps({"host": "localhost", "port": 6379}))

  assert RedisConfig.from_file(path) == RedisConfig(host="localhost", port=6379)


def test_from_file_reads_mqtt(tmp_path):
  path = tmp_path / "mqtt.json"
  path.write_text(dumps({"host": "broker.local", "port": 1883, "keep_alive": 60}))

  config = MQTTConfig.from_file(path)

  assert config.host == "broker.local"
  assert config.keep_alive == 60


def test_from_file_rejects_unknown_keys(tmp_path):
  path = tmp_path / "redis.json"
  path.write_text(dumps({"host": "localhost", "port": 6379, "extra": 1}))

  with pytest.raises(TypeError):
    RedisConfig.from_file(path)


def test_from_file_missing_file_raises(tmp_path):
  with pytest.raises(FileNotFoundError):
    RedisConfig.from_file(tmp_path / "missing.json")


def test_zone_config_requires_all_fields():
  with pytest.raises(TypeError):
    ZoneConfig(name="Bedrooms")


ZONE = {
  "sensor_path": "/home/sensors/a",
  "name": "Bedrooms",
  "outputs": [{"type": "gpio", "pin": "P8_10"}],
  "pid_interval": "10",
  "control_interval": "10",
  "active_low": True,
}


def test_zone_config_accepts_system_config_shape():
  config = ZoneConfig(**ZONE)

  assert config.sensor_path == "/home/sensors/a"
  assert config.outputs == [{"type": "gpio", "pin": "P8_10"}]
  assert config.active_low is True


def test_zone_config_converts_intervals_to_numbers():
  config = ZoneConfig(**ZONE)

  assert config.pid_interval == 10.0
  assert config.control_interval == 10.0


def test_zone_config_defaults_to_active_high():
  zone = {k: v for k, v in ZONE.items() if k != "active_low"}

  assert ZoneConfig(**zone).active_low is False


def test_zone_config_derives_control_path():
  assert ZoneConfig(**ZONE).control_path == "/home/sensors/a/control_value"


def test_zone_config_rejects_legacy_gpio_keys():
  legacy = {**ZONE, "input_gpio": "P8_11", "output_gpio": ["P8_12"]}

  with pytest.raises(TypeError):
    ZoneConfig(**legacy)


def test_every_zone_in_system_config_loads():
  with open("system_config.json") as file:
    zones = json_load(file)["zones"]

  assert [ZoneConfig(**zone).name for zone in zones] == ["Bedrooms", "Common"]

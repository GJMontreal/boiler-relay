from json import dumps

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

from json import dumps, load as json_load
from pathlib import Path

import pytest

from boiler_relay.config import (BoilerConfig, ConfigError, MQTTConfig, PIDConfig, RedisConfig,
                                 SystemConfig, ZoneConfig)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "system_config.json"

VALVE = {"type": "gpio", "pin": "P8_10", "end_switch": "P8_9"}
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}

ZONE = {
  "sensor_path": "/home/sensors/a",
  "name": "Bedrooms",
  "outputs": [VALVE],
  "pid_interval": "10",
  "control_interval": "10",
  "active_low": True,
}

SYSTEM = {
  "redis": {"host": "localhost", "port": 6379},
  "boiler": {"output_gpio": "P8_18"},
  "zones": [ZONE],
}


def system(**changes):
  return {**SYSTEM, **changes}


def zone(**changes):
  return {**ZONE, **changes}


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


def test_boiler_config_defaults():
  config = BoilerConfig(output_gpio="P8_18")

  assert config.active_low is True
  assert config.poll_interval == 5.0


def test_boiler_config_converts_poll_interval():
  assert BoilerConfig(output_gpio="P8_18", poll_interval="10").poll_interval == 10.0


def test_pid_defaults_match_the_tuned_values():
  assert PIDConfig() == PIDConfig(kp=1, ki=0.01, kd=0.5)


def test_zone_config_accepts_the_config_shape():
  config = ZoneConfig(**ZONE)

  assert config.sensor_path == "/home/sensors/a"
  assert config.outputs == [VALVE]
  assert config.active_low is True


def test_zone_config_converts_intervals_to_numbers():
  config = ZoneConfig(**ZONE)

  assert config.pid_interval == 10.0
  assert config.control_interval == 10.0


def test_zone_config_defaults():
  config = ZoneConfig(**{k: v for k, v in ZONE.items() if k not in ("active_low", "control_interval")})

  assert config.active_low is False
  assert config.control_interval == 10.0
  assert config.pid == PIDConfig()


def test_zone_config_reads_pid_gains():
  config = ZoneConfig(**zone(pid={"kp": 2, "ki": 0.1}))

  assert config.pid == PIDConfig(kp=2, ki=0.1, kd=0.5)


def test_zone_config_rejects_unknown_pid_keys():
  with pytest.raises(TypeError):
    ZoneConfig(**zone(pid={"kq": 2}))


def test_zone_config_derives_control_path():
  assert ZoneConfig(**ZONE).control_path == "/home/sensors/a/control_value"


def test_zone_config_lists_end_switches():
  config = ZoneConfig(**zone(outputs=[VALVE, {"type": "gpio", "pin": "P8_14", "end_switch": "P8_17"}, {"type": "gpio", "pin": "P8_16"}]))

  assert config.end_switches == ["P8_9", "P8_17"]


def test_zone_config_rejects_legacy_gpio_keys():
  with pytest.raises(TypeError):
    ZoneConfig(**{**ZONE, "input_gpio": "P8_11", "output_gpio": ["P8_12"]})


def test_zone_config_requires_all_fields():
  with pytest.raises(TypeError):
    ZoneConfig(name="Bedrooms")


def test_zone_config_rejects_mixed_output_types():
  with pytest.raises(ConfigError, match="one type"):
    ZoneConfig(**zone(outputs=[VALVE, RELAY]))


def test_zone_config_rejects_an_output_without_a_type():
  with pytest.raises(ConfigError, match="no type"):
    ZoneConfig(**zone(outputs=[{"pin": "P8_10"}]))


def test_zone_config_rejects_active_low_on_an_output():
  with pytest.raises(ConfigError, match="active_low"):
    ZoneConfig(**zone(outputs=[{**VALVE, "active_low": True}]))


@pytest.mark.parametrize("field", ["pid_interval", "control_interval"])
def test_zone_config_rejects_non_positive_intervals(field):
  with pytest.raises(ConfigError, match="positive"):
    ZoneConfig(**zone(**{field: 0}))


def test_system_config_builds_every_section():
  config = SystemConfig.from_dict(system(mqtt={"host": "localhost", "port": 1883, "keep_alive": 60}))

  assert config.redis.port == 6379
  assert config.boiler.output_gpio == "P8_18"
  assert config.mqtt.host == "localhost"
  assert [z.name for z in config.zones] == ["Bedrooms"]


def test_system_config_mqtt_is_optional():
  assert SystemConfig.from_dict(SYSTEM).mqtt is None


def test_system_config_derives_the_boiler_inputs_from_the_outputs():
  second = zone(name="Common", sensor_path="/home/sensors/b", outputs=[{"type": "gpio", "pin": "P8_8", "end_switch": "P8_7"}])

  config = SystemConfig.from_dict(system(zones=[ZONE, second]))

  assert config.end_switches == ["P8_9", "P8_7"]


@pytest.mark.parametrize("section", ["redis", "boiler", "zones"])
def test_system_config_requires_these_sections(section):
  data = {k: v for k, v in SYSTEM.items() if k != section}

  with pytest.raises(ConfigError, match=section):
    SystemConfig.from_dict(data)


def test_system_config_rejects_the_old_inputs_list():
  with pytest.raises(ConfigError, match="inputs"):
    SystemConfig.from_dict(system(inputs=["P8_7"]))


def test_system_config_names_the_zone_that_is_invalid():
  with pytest.raises(ConfigError, match="Bedrooms"):
    SystemConfig.from_dict(system(zones=[zone(outputs=[VALVE, RELAY])]))


def test_system_config_wraps_a_misspelled_key():
  with pytest.raises(ConfigError, match="boiler"):
    SystemConfig.from_dict(system(boiler={"output_gpio": "P8_18", "control_interval": 10}))


@pytest.mark.parametrize("field", ["name", "sensor_path"])
def test_system_config_rejects_duplicate_zones(field):
  other = zone(name="Common", sensor_path="/home/sensors/b", outputs=[{"type": "gpio", "pin": "P8_8"}])
  other[field] = ZONE[field]

  with pytest.raises(ConfigError, match="duplicate"):
    SystemConfig.from_dict(system(zones=[ZONE, other]))


@pytest.mark.parametrize("clash", [
  {"type": "gpio", "pin": "P8_10"},
  {"type": "gpio", "pin": "P8_8", "end_switch": "P8_9"},
  {"type": "gpio", "pin": "P8_8", "end_switch": "P8_8"},
  {"type": "gpio", "pin": "P8_18"},
])
def test_system_config_rejects_a_pin_used_twice(clash):
  other = zone(name="Common", sensor_path="/home/sensors/b", outputs=[clash])

  with pytest.raises(ConfigError, match="more than once"):
    SystemConfig.from_dict(system(zones=[ZONE, other]))


def test_system_config_from_file_reports_a_missing_file(tmp_path):
  with pytest.raises(ConfigError, match="doesn't exist"):
    SystemConfig.from_file(tmp_path / "missing.json")


def test_system_config_from_file_reports_bad_json(tmp_path):
  path = tmp_path / "config.json"
  path.write_text("{not json")

  with pytest.raises(ConfigError, match="not valid JSON"):
    SystemConfig.from_file(path)


def test_shipped_config_loads_with_every_zone():
  config = SystemConfig.from_file(CONFIG_PATH)

  assert [z.name for z in config.zones] == ["Bedrooms", "Common", "Study", "Kitchen", "BackRoom", "Stairwell"]
  assert config.mqtt is not None


def test_shipped_config_pairs_each_valve_with_its_end_switch():
  config = SystemConfig.from_file(CONFIG_PATH)
  pairs = {(o["pin"], o["end_switch"]) for z in config.zones for o in z.outputs if "end_switch" in o}

  assert pairs == {("P8_10", "P8_9"), ("P8_14", "P8_17"), ("P8_8", "P8_7"),
                   ("P8_12", "P8_11"), ("P8_16", "P8_15"), ("P8_28", "P8_27")}


def test_shipped_stairwell_zone_drives_the_relay_alone():
  config = SystemConfig.from_file(CONFIG_PATH)
  stairwell = next(z for z in config.zones if z.name == "Stairwell")

  assert stairwell.sensor_path == "/home/sensors/stairwell"
  assert [o["type"] for o in stairwell.outputs] == ["MQTTRelay"]
  assert stairwell.end_switches == []

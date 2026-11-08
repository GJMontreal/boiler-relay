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
  "system": "hydronic",
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


def test_the_mqtt_refresh_interval_defaults_to_a_minute():
  assert MQTTConfig(host="broker.local", port=1883, keep_alive=60).refresh_interval == 60.0


def test_the_mqtt_refresh_interval_is_read_from_the_config():
  config = SystemConfig.from_dict(system(mqtt={"host": "h", "port": 1883, "keep_alive": 60, "refresh_interval": 30}))

  assert config.mqtt.refresh_interval == 30.0


@pytest.mark.parametrize("value", [0, -1, "60", None, True, float("inf"), float("nan")])
def test_the_mqtt_refresh_interval_must_be_a_positive_number(value):
  with pytest.raises(ConfigError, match="refresh_interval"):
    MQTTConfig(host="h", port=1883, keep_alive=60, refresh_interval=value)


def test_the_shipped_config_sets_the_mqtt_refresh_interval():
  assert SystemConfig.from_file(CONFIG_PATH).mqtt.refresh_interval == 60.0


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
  assert PIDConfig() == PIDConfig(kp=1, ki=0.01, kd=0.5, integral_cap=1.0)


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


def test_zone_config_reads_the_integral_cap():
  assert ZoneConfig(**zone(pid={"integral_cap": 0.3})).pid.integral_cap == 0.3


@pytest.mark.parametrize("pid", [
  {"kp": -1},
  {"ki": -0.01},
  {"kd": -0.5},
  {"kp": "1"},
  {"ki": True},
  {"kd": None},
  {"kp": float("nan")},
  {"ki": float("inf")},
  {"integral_cap": 1.5},
  {"integral_cap": -0.1},
  {"integral_cap": "0.3"},
  {"integral_cap": float("nan")},
])
def test_zone_config_rejects_nonsense_pid_values(pid):
  with pytest.raises(ConfigError, match="zone Bedrooms: pid"):
    ZoneConfig(**zone(pid=pid))


@pytest.mark.parametrize("pid", [
  {"kp": 0, "ki": 0, "kd": 0},
  {"integral_cap": 0},
  {"integral_cap": 1},
])
def test_zone_config_accepts_the_edges_of_the_pid_ranges(pid):
  ZoneConfig(**zone(pid=pid))


def test_zone_config_rejects_unknown_pid_keys():
  with pytest.raises(TypeError):
    ZoneConfig(**zone(pid={"kq": 2}))


SHADOW_PID = {"kp": 1, "ki": 0.001, "kd": 0, "integral_cap": 0.3}
ELECTRIC_ZONE = {
  "sensor_path": "/home/sensors/b",
  "name": "Stairwell",
  "system": "electric",
  "outputs": [RELAY],
  "pid_interval": "10",
}


def test_a_config_without_a_shadow_section_gives_every_zone_its_own_pid():
  config = SystemConfig.from_dict(system())

  assert config.shadow is None
  assert config.zones_for(True) == config.zones
  assert config.zones_for(False) == config.zones


def test_the_shadow_pid_replaces_the_pid_of_every_hydronic_zone_in_shadow_mode():
  config = SystemConfig.from_dict(system(zones=[ZONE, ELECTRIC_ZONE], shadow={"pid": SHADOW_PID}))

  hydronic, electric = config.zones_for(True)

  assert hydronic.pid == PIDConfig(**SHADOW_PID)
  assert electric.pid == PIDConfig()
  assert hydronic.name == "Bedrooms"


def test_the_shadow_pid_leaves_active_mode_alone():
  config = SystemConfig.from_dict(system(shadow={"pid": SHADOW_PID}))

  assert config.zones_for(False)[0].pid == PIDConfig()
  assert config.zones[0].pid == PIDConfig()


def test_the_shadow_pid_overrides_a_zone_pid_in_shadow_mode_only():
  config = SystemConfig.from_dict(system(zones=[zone(pid={"kp": 3})], shadow={"pid": SHADOW_PID}))

  assert config.zones_for(True)[0].pid == PIDConfig(**SHADOW_PID)
  assert config.zones_for(False)[0].pid == PIDConfig(kp=3)


def test_the_shadow_section_needs_a_pid():
  with pytest.raises(ConfigError, match="shadow"):
    SystemConfig.from_dict(system(shadow={}))


def test_the_shadow_section_rejects_unknown_keys():
  with pytest.raises(ConfigError, match="shadow"):
    SystemConfig.from_dict(system(shadow={"pid": SHADOW_PID, "mode": "x"}))


def test_the_shadow_pid_is_validated():
  with pytest.raises(ConfigError, match="shadow: pid integral_cap"):
    SystemConfig.from_dict(system(shadow={"pid": {"integral_cap": 2}}))


def test_the_shipped_config_runs_candidate_gains_in_the_shadow_only():
  config = SystemConfig.from_file(CONFIG_PATH)
  today = PIDConfig(kp=1, ki=0.01, kd=0.5, integral_cap=1.0)

  assert config.shadow.pid == PIDConfig(**SHADOW_PID)
  assert all(zone.pid == today for zone in config.zones_for(False) if zone.name != "Study")
  assert all(zone.pid == PIDConfig(**SHADOW_PID) for zone in config.zones_for(True) if zone.system == "hydronic")
  assert all(zone.pid == today for zone in config.zones_for(True) if zone.system == "electric")


TOP_PID = {"kp": 2, "ki": 0.02, "kd": 0.1, "integral_cap": 0.5}
TODAY = PIDConfig(kp=1, ki=0.01, kd=0.5, integral_cap=1.0)


def effective(config, shadow):
  return {zone.name: zone.pid for zone in config.zones_for(shadow)}


def test_a_zone_pid_block_wins_over_the_top_level_pid():
  config = SystemConfig.from_dict(system(zones=[zone(pid={"kp": 3})], pid=TOP_PID))

  assert effective(config, False) == {"Bedrooms": PIDConfig(kp=3)}


def test_the_top_level_pid_is_the_default_for_every_zone_without_a_block():
  config = SystemConfig.from_dict(system(zones=[ZONE, ELECTRIC_ZONE], pid=TOP_PID))

  assert effective(config, False) == {"Bedrooms": PIDConfig(**TOP_PID), "Stairwell": PIDConfig(**TOP_PID)}


def test_a_null_zone_pid_falls_back_to_the_top_level_pid():
  config = SystemConfig.from_dict(system(zones=[zone(pid=None)], pid=TOP_PID))

  assert effective(config, False) == {"Bedrooms": PIDConfig(**TOP_PID)}


def test_with_neither_block_a_zone_gets_the_built_in_defaults():
  config = SystemConfig.from_dict(system(zones=[ZONE, ELECTRIC_ZONE]))

  assert config.pid is None
  assert effective(config, False) == {"Bedrooms": TODAY, "Stairwell": TODAY}


def test_shadow_mode_replaces_every_hydronic_zone_whatever_the_zone_or_the_top_level_says():
  zones = [zone(pid={"kp": 3}), zone(name="Study", sensor_path="/home/sensors/c", outputs=[{**VALVE, "pin": "P8_12", "end_switch": "P8_11"}])]
  config = SystemConfig.from_dict(system(zones=zones, pid=TOP_PID, shadow={"pid": SHADOW_PID}))

  assert effective(config, True) == {"Bedrooms": PIDConfig(**SHADOW_PID), "Study": PIDConfig(**SHADOW_PID)}
  assert effective(config, False) == {"Bedrooms": PIDConfig(kp=3), "Study": PIDConfig(**TOP_PID)}


def test_an_electric_zone_in_shadow_mode_follows_the_active_precedence():
  own = {**ELECTRIC_ZONE, "pid": {"kp": 4}}
  shadow = {"pid": SHADOW_PID}

  top = SystemConfig.from_dict(system(zones=[ZONE, ELECTRIC_ZONE], pid=TOP_PID, shadow=shadow))
  block = SystemConfig.from_dict(system(zones=[ZONE, own], pid=TOP_PID, shadow=shadow))
  neither = SystemConfig.from_dict(system(zones=[ZONE, ELECTRIC_ZONE], shadow=shadow))

  assert effective(top, True)["Stairwell"] == PIDConfig(**TOP_PID)
  assert effective(block, True)["Stairwell"] == PIDConfig(kp=4)
  assert effective(neither, True)["Stairwell"] == TODAY


@pytest.mark.parametrize("pid", [
  {"kp": -1},
  {"ki": "0.01"},
  {"kd": float("nan")},
  {"integral_cap": 1.5},
  {"integral_cap": True},
])
def test_an_invalid_top_level_pid_is_rejected_by_name(pid):
  with pytest.raises(ConfigError, match="top-level pid"):
    SystemConfig.from_dict(system(pid=pid))


@pytest.mark.parametrize("pid", [{"kq": 1}, [1, 0.01, 0.5], "1"])
def test_a_malformed_top_level_pid_is_rejected_by_name(pid):
  with pytest.raises(ConfigError, match="top-level pid"):
    SystemConfig.from_dict(system(pid=pid))


def test_the_shipped_config_writes_the_live_gains_out_explicitly():
  with open(CONFIG_PATH) as file:
    data = json_load(file)
  config = SystemConfig.from_file(CONFIG_PATH)

  assert data["pid"] == {"kp": 1, "ki": 0.01, "kd": 0.5, "integral_cap": 1.0}
  assert config.pid == TODAY
  assert all(pid == TODAY for name, pid in effective(config, False).items() if name != "Study")
  assert effective(config, False)["Study"] == PIDConfig(**SHADOW_PID)
  hydronic = {zone.name for zone in config.zones if zone.system == "hydronic"}
  shadow = effective(config, True)
  assert all(shadow[name] == PIDConfig(**SHADOW_PID) for name in hydronic)
  assert all(pid == TODAY for name, pid in shadow.items() if name not in hydronic)


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
  second = zone(name="Common", sensor_path="/home/sensors/b", outputs=[{"type": "gpio", "pin": "P8_8", "end_switch": "P8_15"}])

  config = SystemConfig.from_dict(system(zones=[ZONE, second]))

  assert config.end_switches == ["P8_9", "P8_15"]


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

  assert pairs == {("P8_10", "P8_9"), ("P8_14", "P8_17"), ("P8_8", "P8_15"),
                   ("P8_12", "P8_11"), ("P8_16", "P8_7"), ("P8_28", "P8_27")}


def test_shipped_stairwell_zone_drives_the_relay_alone():
  config = SystemConfig.from_file(CONFIG_PATH)
  stairwell = next(z for z in config.zones if z.name == "Stairwell")

  assert stairwell.sensor_path == "/home/sensors/stairwell"
  assert [o["type"] for o in stairwell.outputs] == ["MQTTRelay"]
  assert stairwell.end_switches == []


@pytest.mark.parametrize("value", ["hydronic", "electric"])
def test_zone_config_accepts_each_system(value):
  outputs = [RELAY] if value == "electric" else [VALVE]

  assert ZoneConfig(**zone(system=value, outputs=outputs)).system == value


def test_zone_config_rejects_an_unknown_system():
  with pytest.raises(ConfigError, match="Bedrooms.*system"):
    ZoneConfig(**zone(system="steam"))


def test_system_config_rejects_a_zone_without_a_system():
  data = {k: v for k, v in ZONE.items() if k != "system"}

  with pytest.raises(ConfigError, match="Bedrooms.*system"):
    SystemConfig.from_dict(system(zones=[data]))


def test_zone_config_rejects_an_electric_zone_with_an_end_switch():
  with pytest.raises(ConfigError, match="electric zone has no end_switch"):
    ZoneConfig(**zone(system="electric", outputs=[VALVE]))


def test_an_electric_zone_may_use_any_output_type():
  electric = zone(name="Stairwell", sensor_path="/home/sensors/s", system="electric", outputs=[RELAY])

  config = SystemConfig.from_dict(system(zones=[ZONE, electric]))

  assert [z.system for z in config.zones] == ["hydronic", "electric"]
  assert config.end_switches == ["P8_9"]


def test_system_config_needs_a_hydronic_zone_with_an_end_switch():
  electric = zone(name="Stairwell", sensor_path="/home/sensors/s", system="electric", outputs=[RELAY])

  with pytest.raises(ConfigError, match="hydronic zone with an end_switch"):
    SystemConfig.from_dict(system(zones=[electric]))


def test_a_hydronic_zone_without_an_end_switch_does_not_satisfy_the_boiler():
  bare = zone(outputs=[{"type": "gpio", "pin": "P8_10"}])

  with pytest.raises(ConfigError, match="hydronic zone with an end_switch"):
    SystemConfig.from_dict(system(zones=[bare]))


def test_shipped_config_marks_only_the_stairwell_electric():
  config = SystemConfig.from_file(CONFIG_PATH)

  assert [z.name for z in config.zones if z.system == "electric"] == ["Stairwell"]


def test_site_name_is_optional():
  assert SystemConfig.from_dict(SYSTEM).site_name is None


def test_site_name_is_read_from_the_config():
  assert SystemConfig.from_dict(system(site_name="Example Site")).site_name == "Example Site"


@pytest.mark.parametrize("name", ["Example Site", "x", "x" * 60, "Café Ünïcode", "  padded  "])
def test_site_name_accepts_a_printable_string(name):
  assert SystemConfig.from_dict(system(site_name=name)).site_name == name


@pytest.mark.parametrize("name", ["", " ", "   ", "x" * 61, "a\tb", "a\nb", "a\x00b", "a\x7fb", "a\x85b", "\n"])
def test_site_name_rejects_a_blank_long_or_control_string(name):
  with pytest.raises(ConfigError) as error:
    SystemConfig.from_dict(system(site_name=name))

  assert str(error.value).startswith("site_name")


@pytest.mark.parametrize("name", [None, 5, 1.5, True, ["Example Site"], {"a": "b"}])
def test_site_name_must_be_a_string(name):
  with pytest.raises(ConfigError) as error:
    SystemConfig.from_dict(system(site_name=name))

  assert str(error.value).startswith("site_name must be a string")


def test_an_unknown_top_level_section_is_still_refused():
  with pytest.raises(ConfigError, match="unknown config sections"):
    SystemConfig.from_dict(system(site_title="Example Site"))


def test_a_config_without_site_name_loads_as_before():
  config = SystemConfig.from_dict(SYSTEM)

  assert config.site_name is None
  assert [z.name for z in config.zones] == ["Bedrooms"]


def test_the_shipped_config_names_the_site_generically():
  assert SystemConfig.from_file(CONFIG_PATH).site_name == "Heating"

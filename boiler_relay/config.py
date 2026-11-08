from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from json import load as json_load
from math import isfinite


class ConfigError(Exception):
  pass

HYDRONIC = "hydronic"
ELECTRIC = "electric"
SYSTEMS = (HYDRONIC, ELECTRIC)

@dataclass 
class Config():
  pass

  @classmethod
  def from_file(cls, file_name) -> Config:
    with open(file_name, 'r') as file:
      data = json_load(file)
    return cls(**data)

@dataclass
class MQTTConfig(Config):
  host: str
  port: int
  keep_alive: float
  refresh_interval: float = 60.0

  def __post_init__(self):
    if not is_number(self.refresh_interval) or self.refresh_interval <= 0:
      raise ConfigError(f"mqtt refresh_interval must be a positive number of seconds, found {self.refresh_interval!r}")
    self.refresh_interval = float(self.refresh_interval)

@dataclass
class RedisConfig(Config):
  host: str
  port: int

@dataclass
class BoilerConfig(Config):
  output_gpio: str
  poll_interval: float = 5.0
  active_low: bool = True

  def __post_init__(self):
    self.poll_interval = float(self.poll_interval)

def is_number(value):
  return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

@dataclass
class PIDConfig(Config):
  kp: float = 1.0
  ki: float = 0.01
  kd: float = 0.5
  integral_cap: float = 1.0

  def __post_init__(self):
    for field in ("kp", "ki", "kd"):
      value = getattr(self, field)
      if not is_number(value) or value < 0:
        raise ConfigError(f"pid {field} must be a number of zero or more, found {value!r}")
    if not is_number(self.integral_cap) or not 0 <= self.integral_cap <= 1:
      raise ConfigError(f"pid integral_cap must be a number from 0 to 1, found {self.integral_cap!r}")

@dataclass
class ZoneConfig(Config):
  sensor_path: str
  name: str
  outputs: list[dict]
  pid_interval: float
  system: str
  control_interval: float = 10.0
  active_low: bool = False
  pid: PIDConfig = None

  def __post_init__(self):
    self.pid_interval = float(self.pid_interval)
    self.control_interval = float(self.control_interval)
    if not isinstance(self.pid, PIDConfig):
      try:
        self.pid = PIDConfig(**(self.pid or {}))
      except ConfigError as error:
        raise ConfigError(f"zone {self.name}: {error}")
    self.validate()

  def validate(self):
    if self.system not in SYSTEMS:
      raise ConfigError(f"zone {self.name}: system must be one of {list(SYSTEMS)}, found {self.system!r}")
    if self.system == ELECTRIC and self.end_switches:
      raise ConfigError(f"zone {self.name}: an electric zone has no end_switch")
    if self.pid_interval <= 0 or self.control_interval <= 0:
      raise ConfigError(f"zone {self.name}: pid_interval and control_interval must be positive")
    for output in self.outputs:
      if "type" not in output:
        raise ConfigError(f"zone {self.name}: output {output} has no type")
      if "active_low" in output:
        raise ConfigError(f"zone {self.name}: active_low belongs on the zone, not on an output")
    types = {output["type"] for output in self.outputs}
    if len(types) > 1:
      raise ConfigError(f"zone {self.name}: outputs must all be one type, found {sorted(types)}")

  @property
  def control_path(self) -> str:
    return f"{self.sensor_path}/control_value"

  @property
  def end_switches(self) -> list[str]:
    return [output["end_switch"] for output in self.outputs if "end_switch" in output]

@dataclass
class RelayConfig(Config):
  device: str
  topic: str

@dataclass
class ShadowConfig(Config):
  pid: PIDConfig

  def __post_init__(self):
    if not isinstance(self.pid, PIDConfig):
      try:
        self.pid = PIDConfig(**(self.pid or {}))
      except ConfigError as error:
        raise ConfigError(f"shadow: {error}")

SECTIONS = {"redis", "boiler", "zones", "mqtt", "shadow", "pid"}

@dataclass
class SystemConfig(Config):
  redis: RedisConfig
  boiler: BoilerConfig
  zones: list[ZoneConfig]
  mqtt: MQTTConfig = None
  shadow: ShadowConfig = None
  pid: PIDConfig = None

  @classmethod
  def from_dict(cls, data: dict) -> SystemConfig:
    unknown = set(data) - SECTIONS
    if unknown:
      raise ConfigError(f"unknown config sections: {sorted(unknown)}")
    for section in ("redis", "boiler", "zones"):
      if section not in data:
        raise ConfigError(f"missing config section: {section}")

    redis = cls.build("redis", RedisConfig, data["redis"])
    boiler = cls.build("boiler", BoilerConfig, data["boiler"])
    mqtt = cls.build("mqtt", MQTTConfig, data["mqtt"]) if "mqtt" in data else None
    pid = cls.build_default_pid(data["pid"]) if "pid" in data else None
    zones = [cls.build_zone(index, entry, pid) for index, entry in enumerate(data["zones"])]

    shadow = cls.build("shadow", ShadowConfig, data["shadow"]) if "shadow" in data else None

    config = cls(redis=redis, boiler=boiler, zones=zones, mqtt=mqtt, shadow=shadow, pid=pid)
    config.validate()
    return config

  @classmethod
  def from_file(cls, file_name) -> SystemConfig:
    try:
      with open(file_name, 'r') as file:
        data = json_load(file)
    except FileNotFoundError:
      raise ConfigError(f"{file_name} doesn't exist")
    except ValueError as error:
      raise ConfigError(f"{file_name} is not valid JSON: {error}")
    return cls.from_dict(data)

  @staticmethod
  def build_default_pid(entry):
    try:
      return PIDConfig(**entry)
    except ConfigError as error:
      raise ConfigError(f"top-level pid: {error}")
    except (TypeError, ValueError) as error:
      raise ConfigError(f"invalid top-level pid config: {error}")

  @classmethod
  def build_zone(cls, index, entry, default_pid):
    zone = cls.build(f"zone {entry.get('name', index)}", ZoneConfig, entry)
    if default_pid is not None and entry.get("pid") is None:
      return replace(zone, pid=default_pid)
    return zone

  @staticmethod
  def build(section, config_class, entry):
    try:
      return config_class(**entry)
    except ConfigError:
      raise
    except (TypeError, ValueError) as error:
      raise ConfigError(f"invalid {section} config: {error}")

  def validate(self):
    for field in ("name", "sensor_path"):
      values = [getattr(zone, field) for zone in self.zones]
      duplicates = sorted({value for value in values if values.count(value) > 1})
      if duplicates:
        raise ConfigError(f"duplicate zone {field}: {duplicates}")

    pins = [self.boiler.output_gpio]
    for zone in self.zones:
      pins += [output["pin"] for output in zone.outputs if "pin" in output]
      pins += zone.end_switches
    duplicates = sorted({pin for pin in pins if pins.count(pin) > 1})
    if duplicates:
      raise ConfigError(f"GPIO pins used more than once: {duplicates}")

    if not any(zone.system == HYDRONIC and zone.end_switches for zone in self.zones):
      raise ConfigError("the boiler needs at least one hydronic zone with an end_switch")

  @property
  def end_switches(self) -> list[str]:
    return [pin for zone in self.zones if zone.system == HYDRONIC for pin in zone.end_switches]

  def zones_for(self, shadow) -> list[ZoneConfig]:
    if not shadow or self.shadow is None:
      return self.zones
    return [replace(zone, pid=self.shadow.pid) if zone.system == HYDRONIC else zone for zone in self.zones]

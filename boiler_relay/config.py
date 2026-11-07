from __future__ import annotations

from dataclasses import dataclass
from json import load as json_load


class ConfigError(Exception):
  pass

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

@dataclass
class PIDConfig(Config):
  kp: float = 1.0
  ki: float = 0.01
  kd: float = 0.5

@dataclass
class ZoneConfig(Config):
  sensor_path: str
  name: str
  outputs: list[dict]
  pid_interval: float
  control_interval: float = 10.0
  active_low: bool = False
  pid: PIDConfig = None

  def __post_init__(self):
    self.pid_interval = float(self.pid_interval)
    self.control_interval = float(self.control_interval)
    if not isinstance(self.pid, PIDConfig):
      self.pid = PIDConfig(**(self.pid or {}))
    self.validate()

  def validate(self):
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

SECTIONS = {"redis", "boiler", "zones", "mqtt"}

@dataclass
class SystemConfig(Config):
  redis: RedisConfig
  boiler: BoilerConfig
  zones: list[ZoneConfig]
  mqtt: MQTTConfig = None

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
    zones = [cls.build(f"zone {entry.get('name', index)}", ZoneConfig, entry)
             for index, entry in enumerate(data["zones"])]

    config = cls(redis=redis, boiler=boiler, zones=zones, mqtt=mqtt)
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

  @property
  def end_switches(self) -> list[str]:
    return [pin for zone in self.zones for pin in zone.end_switches]

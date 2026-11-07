from __future__ import annotations

from dataclasses import dataclass
from json import load as json_load


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
class OutputConfig(Config):
  pass

@dataclass
class ZoneConfig(Config):
  sensor_path: str
  name: str
  outputs: list[dict]
  pid_interval: float
  control_interval: float
  active_low: bool = False

  def __post_init__(self):
    self.pid_interval = float(self.pid_interval)
    self.control_interval = float(self.control_interval)

  @property
  def control_path(self) -> str:
    return f"{self.sensor_path}/control_value"

@dataclass
class RelayConfig(Config):
  device_name: str
  topic: str

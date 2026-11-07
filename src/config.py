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
  input_path: str
  output_path: str
  name: str
  pid_interval: float
  control_interval: float

@dataclass
class RelayConfig(Config):
  device_name: str
  topic: str

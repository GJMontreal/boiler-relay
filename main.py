from __future__ import annotations
from argparse import ArgumentParser, Namespace
from src.boiler_thread import BoilerThread
from src.config import BoilerConfig, MQTTConfig, RedisConfig, ZoneConfig
from src.zone import Zone

from json import load
from unopt import *
from importlib import import_module
from pprint import pprint

def read_config(config_path) -> Namespace | None:
  try:
     file = open(config_path, 'r')
  except FileNotFoundError:
     print(f"{config_path} doesn't exist")
  else:
    with file:
      data = load(file)
      return Namespace(**data)

def parse_arguments() -> Namespace:
  parser = ArgumentParser(description='Get config file path')
  parser.add_argument('--config', '-c', help = 'config file', default='config.json')
  args = parser.parse_args()
  return args

def create_output(output_config,config):
  if "type" not in output_config:
    print("missing output type")
    return
  
  module = import_module("src.actuator")
  type_name = output_config["type"]
  try:
    class_type = getattr(module, type_name)
  except:
    print(f"Unsupported output type: {type_name}")
    return
  
  instance = class_type(config)
  return instance
  
def create_zone(zone_config, redis_config):

  try:
    zone = Zone(ZoneConfig(**zone_config),redis_config)
    return zone
  except Exception as error:
    print(f"Failed to create zone. {error}")
    pprint(zone_config)


if __name__ == "__main__":
  args = parse_arguments()
  try:
    config = unwrap(read_config(args.config))
  except:
    print("Missing configuration! Exiting")
    exit()

  try:
    mqtt_config = MQTTConfig(**config.mqtt)
  except:
    print("Missing MQTT configuation")
    mqtt_config = None

  try:
    redis_config = RedisConfig(**config.redis)
  except:
    print("Missing Redis configuration! Exiting")
    exit()

  try:
    boiler_config = BoilerConfig(**config.boiler)
  except:
    print("Missing boiler configuration")
    boiler_config = None

  zones = [create_zone(zone, redis_config) for zone in config.zones]
  [zone.start() for zone in zones if zone is not None]
  if boiler_config is not None:
    BoilerThread(boiler_config, getattr(config, "inputs", [])).start()
  print(f"MQTT {mqtt_config}")
  print(f"Redis {redis_config}")

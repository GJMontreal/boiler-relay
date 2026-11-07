import logging
import signal
import sys
from argparse import ArgumentParser
from pathlib import Path
from threading import Event

from redis import Redis
from redis.exceptions import RedisError

from boiler_relay.boiler_thread import BoilerThread, ShadowBoilerThread
from boiler_relay.config import ConfigError, SystemConfig
from boiler_relay.state_publisher import ACTIVE, SHADOW, StatePublisher, publish_version
from boiler_relay.version import describe
from boiler_relay.zone import Zone

log = logging.getLogger("boiler_relay")

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "system_config.json"

def parse_arguments(argv=None):
  parser = ArgumentParser(description='Get config file path')
  parser.add_argument('--config', '-c', help = 'config file', default=str(DEFAULT_CONFIG))
  parser.add_argument('--version', action = 'version', version = describe())
  parser.add_argument('--shadow', action = 'store_true', help = 'decide without driving any output and publish under heating/shadow/')
  return parser.parse_args(argv)

def build(system, shadow=False):
  mode = SHADOW if shadow else ACTIVE
  zones = [Zone(zone, system.redis, system.mqtt, mode=mode) for zone in system.zones]
  publisher = StatePublisher(Redis(host=system.redis.host, port=system.redis.port, db=0), mode)
  if shadow:
    boiler = ShadowBoilerThread(system.boiler, zones, publisher)
  else:
    boiler = BoilerThread(system.boiler, system.end_switches, publisher)
  return zones, boiler

def announce(redis_config):
  try:
    publish_version(Redis(host=redis_config.host, port=redis_config.port, db=0))
  except RedisError as error:
    log.warning("could not publish the version: %s", error)

def supervise(threads, stop, poll=1.0):
  while not stop.is_set():
    dead = [thread.name for thread in threads if not thread.is_alive()]
    if dead:
      log.error("thread stopped: %s", ", ".join(dead))
      return 1
    stop.wait(poll)
  return 0

def shutdown(zones, boiler):
  boiler.shutdown()
  for zone in zones:
    zone.shutdown()

def main(argv=None):
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
  args = parse_arguments(argv)

  try:
    system = SystemConfig.from_file(args.config)
    zones, boiler = build(system, args.shadow)
  except (ConfigError, ValueError, KeyError) as error:
    log.error("invalid configuration: %s", error)
    return 2

  stop = Event()
  signal.signal(signal.SIGTERM, lambda *_: stop.set())
  signal.signal(signal.SIGINT, lambda *_: stop.set())

  announce(system.redis)
  for zone in zones:
    zone.start()
  boiler.start()
  log.info("started %d zones and the boiler in %s mode", len(zones), SHADOW if args.shadow else ACTIVE)

  code = supervise(zones + [boiler], stop)
  shutdown(zones, boiler)
  return code

if __name__ == "__main__":
  sys.exit(main())

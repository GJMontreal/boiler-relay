import logging
import signal
import sys
from argparse import ArgumentParser
from pathlib import Path
from threading import Event

from boiler_relay.boiler_thread import BoilerThread
from boiler_relay.config import ConfigError, SystemConfig
from boiler_relay.zone import Zone

log = logging.getLogger("boiler_relay")

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "system_config.json"

def parse_arguments(argv=None):
  parser = ArgumentParser(description='Get config file path')
  parser.add_argument('--config', '-c', help = 'config file', default=str(DEFAULT_CONFIG))
  return parser.parse_args(argv)

def build(system):
  zones = [Zone(zone, system.redis, system.mqtt) for zone in system.zones]
  boiler = BoilerThread(system.boiler, system.end_switches)
  return zones, boiler

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
    zones, boiler = build(system)
  except (ConfigError, ValueError, KeyError) as error:
    log.error("invalid configuration: %s", error)
    return 2

  stop = Event()
  signal.signal(signal.SIGTERM, lambda *_: stop.set())
  signal.signal(signal.SIGINT, lambda *_: stop.set())

  for zone in zones:
    zone.start()
  boiler.start()
  log.info("started %d zones and the boiler", len(zones))

  code = supervise(zones + [boiler], stop)
  shutdown(zones, boiler)
  return code

if __name__ == "__main__":
  sys.exit(main())

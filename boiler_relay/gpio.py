import logging

log = logging.getLogger(__name__)

try:
  import Adafruit_BBIO.GPIO as GPIO
except (ImportError, RuntimeError):
  log.warning('Adafruit_BBIO is not available, using stub GPIO')

  class GPIO():
    OUT = 1
    IN = 0

    LOW = 0
    HIGH = 1

    @classmethod
    def setup(cls, pin, state):
      log.debug('gpio setup')

    @classmethod
    def cleanup(cls):
      log.debug('gpio cleanup')

    @classmethod
    def output(cls, pin, state):
      log.debug('gpio output')

    @classmethod
    def input(cls, pin):
      return 0

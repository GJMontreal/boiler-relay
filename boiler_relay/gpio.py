import logging

log = logging.getLogger(__name__)


class StubGPIO():
  OUT = 1
  IN = 0

  LOW = 0
  HIGH = 1

  PUD_OFF = 0
  PUD_DOWN = 1
  PUD_UP = 2

  @classmethod
  def setup(cls, pin, state, pull_up_down=PUD_OFF):
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


class GPIOLoader():
  def __init__(self):
    self.backend = None

  def use_stub(self):
    if self.backend is not None and self.backend is not StubGPIO:
      raise RuntimeError("the real GPIO is already loaded")
    self.backend = StubGPIO

  def load(self):
    if self.backend is None:
      self.backend = self.import_backend()
    return self.backend

  @staticmethod
  def import_backend():
    try:
      import Adafruit_BBIO.GPIO as backend
    except (ImportError, RuntimeError):
      log.warning('Adafruit_BBIO is not available, using stub GPIO')
      return StubGPIO
    return backend

  def __getattr__(self, name):
    return getattr(self.load(), name)


GPIO = GPIOLoader()

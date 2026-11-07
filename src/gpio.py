try:
  import Adafruit_BBIO.GPIO as GPIO
except (ImportError, RuntimeError):
  print('Adafruit_BBIO is not available, using stub GPIO')

  class GPIO():
    OUT = 1
    IN = 0

    LOW = 0
    HIGH = 1

    @classmethod
    def setup(cls, pin, state):
      print('gpio setup')

    @classmethod
    def cleanup(cls):
      print('gpio cleanup')

    @classmethod
    def output(cls, pin, state):
      print('gpio output')

    @classmethod
    def input(cls, pin):
      return 0

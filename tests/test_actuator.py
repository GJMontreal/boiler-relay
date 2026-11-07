from src.actuator import Actuator
from src.config import RedisConfig

REDIS = RedisConfig(host="localhost", port=6379)


class Recording(Actuator):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.values = []

  def activate(self, value):
    self.values.append(value)
    self.should_run = False


def test_run_passes_redis_value_to_activate(redis_client):
  redis_client.set("/home/sensors/a/value", "0.75")
  actuator = Recording("/home/sensors/a", REDIS, update_interval=0)
  actuator.should_run = True

  actuator.run()

  assert actuator.values == [0.75]


def test_run_skips_when_no_value(redis_client):
  actuator = Recording("/home/sensors/a", REDIS, update_interval=0)
  actuator.should_run = True
  calls = []

  original = actuator.redis.get

  def get(topic):
    calls.append(topic)
    if len(calls) == 3:
      actuator.should_run = False
    return original(topic)

  actuator.redis.get = get
  actuator.run()

  assert actuator.values == []
  assert len(calls) == 3


def test_run_survives_unparseable_value(redis_client):
  redis_client.set("/home/sensors/a/value", "not a number")
  actuator = Recording("/home/sensors/a", REDIS, update_interval=0)
  actuator.should_run = True
  calls = []
  original = actuator.redis.get

  def get(topic):
    calls.append(topic)
    if len(calls) == 2:
      actuator.should_run = False
    return original(topic)

  actuator.redis.get = get
  actuator.run()

  assert actuator.values == []


def test_stop_clears_should_run(redis_client):
  actuator = Actuator("/home/sensors/a", REDIS)
  actuator.should_run = True

  actuator.stop()

  assert actuator.should_run is False

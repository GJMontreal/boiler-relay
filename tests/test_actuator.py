from src.actuator import Actuator, MQTTRelay, create_output
from src.config import MQTTConfig, RedisConfig

REDIS = RedisConfig(host="localhost", port=6379)
MQTT = MQTTConfig(host="broker.local", port=1883, keep_alive=60)
RELAY = {"type": "MQTTRelay", "topic": "cmnd/x/ZbSend", "device": "0xB5EA"}


class Recording(Actuator):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.values = []

  def activate(self, value):
    self.values.append(value)
    self.should_run = False


def test_run_passes_redis_value_to_activate(redis_client):
  redis_client.set("/home/sensors/a/heating_cooling_state", "0.75")
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
  redis_client.set("/home/sensors/a/heating_cooling_state", "not a number")
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


def test_create_output_builds_the_named_actuator(redis_client):
  actuator = create_output(RELAY, "/home/sensors/a", REDIS, MQTT)

  assert isinstance(actuator, MQTTRelay)
  assert actuator.path == "/home/sensors/a"
  assert actuator.mqtt_config is MQTT
  assert actuator.relay_config.device == "0xB5EA"
  assert actuator.relay_config.topic == "cmnd/x/ZbSend"


def test_create_output_without_type_returns_none(redis_client):
  assert create_output({"topic": "cmnd/x"}, "/home/sensors/a", REDIS, MQTT) is None


def test_create_output_with_unknown_type_returns_none(redis_client):
  assert create_output({"type": "Toaster"}, "/home/sensors/a", REDIS, MQTT) is None


def test_create_output_ignores_names_that_are_not_actuators(redis_client):
  assert create_output({"type": "Redis"}, "/home/sensors/a", REDIS, MQTT) is None


def test_relay_prints_the_device_message(redis_client, capsys):
  relay = create_output(RELAY, "/home/sensors/a", REDIS, MQTT)

  relay.activate(1.0)

  assert "'Device': '0xB5EA'" in capsys.readouterr().out


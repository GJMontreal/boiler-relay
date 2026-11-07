from src.config import MQTTConfig, RedisConfig, RelayConfig
from json import dumps, load
from redis import Redis
from threading import Thread
from time import sleep
from paho.mqtt import client as mqtt_client

class Actuator():
  def  __init__(self, path, redis_config: RedisConfig, mqtt_config: MQTTConfig = None, output_config: dict = None, update_interval = 0.5) -> None:
    self.path = path
    self.redis = Redis(host=redis_config.host, port=redis_config.port,db=0)
    self.mqtt_config = mqtt_config
    self.output_config = output_config
    self.should_run = False
    self.update_interval = update_interval

  def start(self):
    self.should_run = True
    print(f"starting {self.path}")
    self.thread = Thread(target = self.run)
    self.thread.start()
  
  def stop(self):
    print(f"stopping {self.path}")
    self.should_run = False

  def run(self):
    while self.should_run == True:
      sleep(self.update_interval)

      topic = f'{self.path}/heating_cooling_state'
      message = self.redis.get(topic)
      if message is None:
        continue

      try:
        value = float(message.decode('utf-8'))
        self.activate(value = value)
      except:
        print("error")

  # it's up to concrete implementations to do something useful here
  def activate(self, value):
    print(f"{self.path}.value = {value}")

# {"Device":"0xB5EA","Send":{"Power":0}}
class MQTTRelay(Actuator):
  def __init__(self, path, redis_config: RedisConfig, mqtt_config: MQTTConfig, output_config: dict, update_interval=0.5) -> None:
    super().__init__(path, redis_config, mqtt_config, output_config, update_interval)
    self.relay_config = RelayConfig(topic=output_config["topic"], device=output_config["device"])

  def activate(self, value):
    # we can use json to make this easier to encode
    message = {"Device":self.relay_config.device,
               "Send":{"Power":value}}
    print(message)

def create_output(output_config, path, redis_config, mqtt_config):
  if "type" not in output_config:
    print("missing output type")
    return

  type_name = output_config["type"]
  output_types = {cls.__name__: cls for cls in Actuator.__subclasses__()}
  if type_name not in output_types:
    print(f"Unsupported output type: {type_name}")
    return

  return output_types[type_name](path, redis_config, mqtt_config, output_config)

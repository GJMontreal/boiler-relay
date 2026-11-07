from src.config import MQTTConfig, RelayConfig
from src.gpio import GPIO
from json import dumps
from threading import Event, Lock, Thread
from paho.mqtt import client as mqtt_client

class Actuator():
  output_type = None

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    self.output_config = output_config
    self.mqtt_config = mqtt_config

  def start(self):
    pass

  def stop(self):
    pass

  # it's up to concrete implementations to do something useful here
  def activate(self, value):
    print(f"{self.output_config}.value = {value}")

class GPIOOutput(Actuator):
  output_type = "gpio"

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    super().__init__(output_config, mqtt_config)
    self.pin = output_config["pin"]
    self.active_low = output_config.get("active_low", False)
    self.config_gpio()

  def config_gpio(self):
    print(f'configuring GPIO: {self.pin} as Output')
    GPIO.setup(self.pin, GPIO.OUT)
    output = GPIO.LOW
    if self.active_low:
      output = GPIO.HIGH
    GPIO.output(self.pin, output)
    GPIO.cleanup()

  def activate(self, value):
    output = 1 if value else 0
    if self.active_low:
      output = output * -1 + 1
    GPIO.output(self.pin, output)

# {"Device":"0xB5EA","Send":{"Power":0}}
class MQTTRelay(Actuator):
  output_type = "MQTTRelay"

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    super().__init__(output_config, mqtt_config)
    self.relay_config = RelayConfig(topic=output_config["topic"], device=output_config["device"])
    self.client = None
    self.latest = None
    self.pending = Event()
    self.lock = Lock()
    self.should_run = False

  def start(self):
    self.should_run = True
    self.thread = Thread(target = self.run, daemon = True)
    self.thread.start()

  def stop(self):
    self.should_run = False
    self.pending.set()

  def activate(self, value):
    with self.lock:
      self.latest = value
    self.pending.set()

  def run(self):
    while self.should_run:
      self.pending.wait()
      with self.lock:
        value = self.latest
        self.pending.clear()
      if self.should_run:
        self.send(value)

  def connect(self):
    if self.mqtt_config is None:
      raise ValueError("missing MQTT configuration")
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    client.connect(self.mqtt_config.host, self.mqtt_config.port, int(self.mqtt_config.keep_alive))
    client.loop_start()
    return client

  def send(self, value):
    message = {"Device":self.relay_config.device,
               "Send":{"Power":1 if value else 0}}
    try:
      if self.client is None:
        self.client = self.connect()
      self.client.publish(self.relay_config.topic, dumps(message))
    except Exception as error:
      print(f"MQTT send failed for {self.relay_config.device}: {error}")

def create_output(output_config, mqtt_config):
  if "type" not in output_config:
    print("missing output type")
    return

  type_name = output_config["type"]
  output_types = {cls.output_type: cls for cls in Actuator.__subclasses__() if cls.output_type}
  if type_name not in output_types:
    print(f"Unsupported output type: {type_name}")
    return

  return output_types[type_name](output_config, mqtt_config)

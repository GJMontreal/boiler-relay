import logging
from json import dumps
from threading import Event, Lock, Thread

from paho.mqtt import client as mqtt_client

from boiler_relay.config import MQTTConfig, RelayConfig
from boiler_relay.outputs.actuator import Actuator

log = logging.getLogger(__name__)

SEND_TIMEOUT = 2

# {"Device":"0xB5EA","Send":{"Power":0}}
class MQTTRelay(Actuator):
  output_type = "MQTTRelay"

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    if mqtt_config is None:
      raise ValueError("an MQTTRelay output needs an mqtt section in the config")
    super().__init__(output_config, mqtt_config)
    self.relay_config = RelayConfig(topic=output_config["topic"], device=output_config["device"])
    self.client = None
    self.latest = None
    self.failing = False
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
    thread = getattr(self, "thread", None)
    if thread is not None and thread.is_alive():
      thread.join(SEND_TIMEOUT * 2)
    self.disconnect()

  def activate(self, value):
    with self.lock:
      self.latest = value
    self.pending.set()

  def deactivate(self, wait=False):
    if wait:
      self.send(0, wait=True)
    else:
      self.activate(0)

  def run(self):
    while self.should_run:
      self.pending.wait()
      with self.lock:
        value = self.latest
        self.pending.clear()
      if self.should_run:
        self.send(value)

  def connect(self):
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    client.connect(self.mqtt_config.host, self.mqtt_config.port, int(self.mqtt_config.keep_alive))
    client.loop_start()
    return client

  def disconnect(self):
    if self.client is None:
      return
    try:
      self.client.loop_stop()
      self.client.disconnect()
    except Exception as error:
      log.warning("MQTT disconnect failed for %s: %s", self.relay_config.device, error)
    self.client = None

  def send(self, value, wait=False):
    message = {"Device":self.relay_config.device,
               "Send":{"Power":1 if value else 0}}
    try:
      if self.client is None:
        self.client = self.connect()
      info = self.client.publish(self.relay_config.topic, dumps(message))
      if wait and info is not None:
        info.wait_for_publish(timeout=SEND_TIMEOUT)
    except Exception as error:
      if not self.failing:
        log.warning("MQTT send failed for %s: %s", self.relay_config.device, error)
      self.failing = True
    else:
      if self.failing:
        log.info("MQTT send recovered for %s", self.relay_config.device)
      self.failing = False

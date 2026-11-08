import logging
from json import dumps, loads
from threading import Event, Lock, Thread
from time import monotonic

from paho.mqtt import client as mqtt_client

from boiler_relay.config import MQTTConfig, RelayConfig
from boiler_relay.outputs.actuator import Actuator
from boiler_relay.state_publisher import now

log = logging.getLogger(__name__)

SEND_TIMEOUT = 2
CONFIRM_TIMEOUT = 5
RETRY_CAP = 120


def report_topic(command_topic):
  parts = command_topic.split("/")
  if len(parts) == 3 and parts[0] == "cmnd" and parts[1]:
    return f"tele/{parts[1]}/+/SENSOR"
  return None


def is_count(value):
  return isinstance(value, int) and not isinstance(value, bool)


def parse_report(payload, device):
  try:
    body = loads(payload)
  except (TypeError, ValueError):
    return None
  received = body.get("ZbReceived") if isinstance(body, dict) else None
  if not isinstance(received, dict):
    return None
  for report in received.values():
    if not isinstance(report, dict) or str(report.get("Device", "")).upper() != device.upper():
      continue
    power = report.get("Power")
    if not is_count(power) or power not in (0, 1):
      return None
    link_quality = report.get("LinkQuality")
    return power, link_quality if is_count(link_quality) else None
  return None


# {"Device":"0xB5EA","Send":{"Power":0}}
class MQTTRelay(Actuator):
  output_type = "MQTTRelay"

  def __init__(self, output_config: dict, mqtt_config: MQTTConfig = None) -> None:
    if mqtt_config is None:
      raise ValueError("an MQTTRelay output needs an mqtt section in the config")
    super().__init__(output_config, mqtt_config)
    self.relay_config = RelayConfig(topic=output_config["topic"], device=output_config["device"])
    self.report_topic = report_topic(self.relay_config.topic)
    self.clock = monotonic
    self.client = None
    self.latest = None
    self.failing = False
    self.last_sent = None
    self.sent_at = None
    self.attempts = 0
    self.awaiting = False
    self.mismatch = False
    self.silent = False
    self.confirmed = None
    self.confirmed_time = None
    self.link_quality = None
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
      due = self.due(1 if value else 0)
    if due:
      self.pending.set()

  def due(self, power):
    if self.last_sent is None or self.failing or self.mismatch or power != self.last_sent:
      return True
    if not self.awaiting:
      return False
    waited = self.clock() - self.sent_at
    if waited < self.retry_delay():
      return False
    if not self.silent:
      log.warning("no report from relay %s %d seconds after a command, resending",
                  self.relay_config.device, waited)
      self.silent = True
    return True

  def retry_delay(self):
    return min(CONFIRM_TIMEOUT * 2 ** (self.attempts - 1), RETRY_CAP)

  def status(self):
    with self.lock:
      return {"confirmed": self.confirmed, "confirmed_time": self.confirmed_time}

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
    client.on_connect = self.on_connect
    client.on_message = self.on_message
    client.connect(self.mqtt_config.host, self.mqtt_config.port, int(self.mqtt_config.keep_alive))
    client.loop_start()
    return client

  def on_connect(self, client, userdata, flags, reason_code, properties=None):
    if getattr(reason_code, "is_failure", False) or self.report_topic is None:
      return
    client.subscribe(self.report_topic)

  def on_message(self, client, userdata, message):
    report = parse_report(message.payload, self.relay_config.device)
    if report is None:
      return
    power, link_quality = report
    with self.lock:
      if power != self.confirmed:
        log.info("relay %s reports power %d", self.relay_config.device, power)
      self.confirmed = power
      self.confirmed_time = now()
      self.link_quality = link_quality
      if self.last_sent is None:
        return
      if power == self.last_sent:
        self.awaiting = False
        self.attempts = 0
        self.mismatch = False
        if self.silent:
          log.info("relay %s is reporting again", self.relay_config.device)
          self.silent = False
      else:
        self.mismatch = True
        log.info("relay %s reports power %d after a command for %d, resending",
                 self.relay_config.device, power, self.last_sent)

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
    power = 1 if value else 0
    message = {"Device":self.relay_config.device,
               "Send":{"Power":power}}
    with self.lock:
      repeat = self.awaiting and power == self.last_sent
      self.attempts = self.attempts + 1 if repeat else 1
      self.last_sent = power
      self.sent_at = self.clock()
      self.awaiting = self.report_topic is not None
      self.mismatch = False
    try:
      if self.client is None:
        self.client = self.connect()
      info = self.client.publish(self.relay_config.topic, dumps(message))
      if getattr(info, "rc", 0) != 0:
        raise ConnectionError(f"publish returned code {info.rc}")
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

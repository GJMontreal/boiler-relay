import logging
import signal
from threading import Event

import pytest

from boiler_relay import __main__ as entry
from boiler_relay.config import SystemConfig

VALID = {
  "redis": {"host": "localhost", "port": 6379},
  "boiler": {"output_gpio": "P8_18"},
  "zones": [{
    "sensor_path": "/home/sensors/a",
    "name": "Bedrooms",
    "system": "hydronic",
    "outputs": [{"type": "gpio", "pin": "P8_10", "end_switch": "P8_9"}],
    "pid_interval": 10,
  }],
}


class FakeThread:
  def __init__(self, name="thread", alive=True):
    self.name = name
    self.alive = alive
    self.started = False
    self.shut_down = False

  def is_alive(self):
    return self.alive

  def start(self):
    self.started = True

  def shutdown(self):
    self.shut_down = True


@pytest.fixture
def fakes(monkeypatch):
  created = type("Created", (), {"zones": [], "boilers": []})

  def make_zone(zone_config, redis_config, mqtt_config, mode="active"):
    zone = FakeThread(zone_config.name)
    zone.mode = mode
    created.zones.append(zone)
    return zone

  def make_boiler(boiler_config, end_switches, publisher):
    boiler = FakeThread("boiler")
    boiler.end_switches = end_switches
    boiler.publisher = publisher
    created.boilers.append(boiler)
    return boiler

  def make_shadow_boiler(boiler_config, zones, publisher):
    boiler = FakeThread("boiler")
    boiler.zones = zones
    boiler.publisher = publisher
    created.boilers.append(boiler)
    return boiler

  monkeypatch.setattr(entry, "Zone", make_zone)
  monkeypatch.setattr(entry, "BoilerThread", make_boiler)
  monkeypatch.setattr(entry, "ShadowBoilerThread", make_shadow_boiler)
  monkeypatch.setattr(entry.signal, "signal", lambda *args: None)
  return created


def write_config(tmp_path, data):
  from json import dumps
  path = tmp_path / "config.json"
  path.write_text(dumps(data))
  return str(path)


def test_the_default_config_is_the_shipped_one():
  assert entry.parse_arguments([]).config == str(entry.DEFAULT_CONFIG)
  assert entry.DEFAULT_CONFIG.exists()
  SystemConfig.from_file(entry.DEFAULT_CONFIG)


def test_a_config_flag_overrides_the_default():
  assert entry.parse_arguments(["-c", "other.json"]).config == "other.json"


def test_build_creates_a_thread_per_zone_and_the_boiler(fakes):
  system = SystemConfig.from_dict(VALID)

  zones, boiler = entry.build(system)

  assert [zone.name for zone in zones] == ["Bedrooms"]
  assert boiler.end_switches == ["P8_9"]


def test_the_shadow_flag_is_off_by_default():
  assert entry.parse_arguments([]).shadow is False
  assert entry.parse_arguments(["--shadow"]).shadow is True


def test_build_makes_active_threads_that_publish_under_active(fakes):
  system = SystemConfig.from_dict(VALID)

  zones, boiler = entry.build(system)

  assert zones[0].mode == "active"
  assert boiler.publisher.prefix == "boiler_relay/active"


def test_build_in_shadow_mode_makes_a_boiler_that_follows_the_zones(fakes):
  system = SystemConfig.from_dict(VALID)

  zones, boiler = entry.build(system, shadow=True)

  assert zones[0].mode == "shadow"
  assert boiler.zones == zones
  assert boiler.publisher.prefix == "boiler_relay/shadow"
  assert not hasattr(boiler, "end_switches")


def test_supervise_returns_zero_when_asked_to_stop():
  stop = Event()
  stop.set()

  assert entry.supervise([FakeThread()], stop) == 0


def test_supervise_returns_one_when_a_thread_has_stopped(caplog):
  threads = [FakeThread("Bedrooms"), FakeThread("Kitchen", alive=False)]

  with caplog.at_level(logging.ERROR, logger="boiler_relay"):
    code = entry.supervise(threads, Event(), poll=0)

  assert code == 1
  assert "Kitchen" in caplog.text


def test_supervise_keeps_waiting_while_threads_live():
  stop = Event()
  threads = [FakeThread()]
  polls = []

  def stop_after_two(timeout):
    polls.append(timeout)
    if len(polls) == 2:
      stop.set()

  stop.wait = stop_after_two

  assert entry.supervise(threads, stop, poll=0.5) == 0
  assert polls == [0.5, 0.5]


def test_main_exits_two_on_a_missing_config(tmp_path, caplog):
  with caplog.at_level(logging.ERROR, logger="boiler_relay"):
    code = entry.main(["-c", str(tmp_path / "missing.json")])

  assert code == 2
  assert "invalid configuration" in caplog.text


def test_main_exits_two_on_an_invalid_config(tmp_path, fakes):
  bad = {**VALID, "inputs": ["P8_7"]}

  assert entry.main(["-c", write_config(tmp_path, bad)]) == 2
  assert fakes.zones == []


def test_main_exits_two_when_a_zone_cannot_be_built(tmp_path, monkeypatch, caplog):
  def refuse(*args, **kwargs):
    raise ValueError("unsupported output type: Toaster")

  monkeypatch.setattr(entry, "Zone", refuse)

  with caplog.at_level(logging.ERROR, logger="boiler_relay"):
    code = entry.main(["-c", write_config(tmp_path, VALID)])

  assert code == 2
  assert "Toaster" in caplog.text


def test_main_starts_everything_and_shuts_down_cleanly(tmp_path, fakes, monkeypatch):
  monkeypatch.setattr(entry, "supervise", lambda threads, stop: 0)

  code = entry.main(["-c", write_config(tmp_path, VALID)])

  assert code == 0
  assert fakes.zones[0].started and fakes.boilers[0].started
  assert fakes.zones[0].shut_down and fakes.boilers[0].shut_down


def test_main_returns_one_and_still_shuts_down_when_a_thread_dies(tmp_path, fakes, monkeypatch):
  monkeypatch.setattr(entry, "supervise", lambda threads, stop: 1)

  code = entry.main(["-c", write_config(tmp_path, VALID)])

  assert code == 1
  assert fakes.zones[0].shut_down and fakes.boilers[0].shut_down


def test_main_stops_on_sigterm_and_sigint(tmp_path, fakes, monkeypatch):
  handlers = {}
  monkeypatch.setattr(entry.signal, "signal", lambda number, handler: handlers.update({number: handler}))

  def stopped_by_signal(threads, stop):
    handlers[signal.SIGTERM]()
    return 0 if stop.is_set() else 1

  monkeypatch.setattr(entry, "supervise", stopped_by_signal)

  assert entry.main(["-c", write_config(tmp_path, VALID)]) == 0
  assert set(handlers) == {signal.SIGTERM, signal.SIGINT}

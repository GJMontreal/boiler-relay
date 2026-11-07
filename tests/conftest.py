import fakeredis
import pytest

from src import actuator, output_thread, zone_valve_thread


class StopLoop(Exception):
  pass


@pytest.fixture
def redis_server():
  return fakeredis.FakeServer()


@pytest.fixture
def redis_client(redis_server, monkeypatch):
  def make_client(*args, **kwargs):
    return fakeredis.FakeRedis(server=redis_server)

  monkeypatch.setattr(actuator, "Redis", make_client)
  monkeypatch.setattr(zone_valve_thread, "Redis", make_client)
  monkeypatch.setattr(output_thread.redis, "Redis", make_client)
  return make_client()


@pytest.fixture
def run_ticks(monkeypatch):
  def run(thread, ticks):
    count = 0

    def fake_sleep(_):
      nonlocal count
      count += 1
      if count >= ticks:
        raise StopLoop

    monkeypatch.setattr(zone_valve_thread, "sleep", fake_sleep)
    monkeypatch.setattr(output_thread.time, "sleep", fake_sleep)
    with pytest.raises(StopLoop):
      thread.run()

  return run


@pytest.fixture
def gpio(monkeypatch):
  calls = []

  class RecordingGPIO:
    OUT = 1
    IN = 0
    LOW = 0
    HIGH = 1

    @classmethod
    def setup(cls, pin, state):
      pass

    @classmethod
    def cleanup(cls):
      pass

    @classmethod
    def output(cls, pin, state):
      calls.append((pin, state))

    @classmethod
    def input(cls, pin):
      return 0

  monkeypatch.setattr(zone_valve_thread, "GPIO", RecordingGPIO)
  monkeypatch.setattr(output_thread, "GPIO", RecordingGPIO)
  return calls

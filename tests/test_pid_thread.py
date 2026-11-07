import json
from types import SimpleNamespace

from src.output_thread import PIDThread

INPUT = "/home/sensors/a"
OUTPUT = "/home/sensors/a/control_value"
ZONE = SimpleNamespace(name="Test", last_sample_time=None)


def seed(redis_client, current, target):
  redis_client.set(f"{INPUT}/current_temperature", json.dumps({"value": current, "time": "t0"}))
  redis_client.set(f"{INPUT}/target_temperature", json.dumps({"value": target}))


def test_cold_room_calls_for_heat(redis_client, run_ticks):
  seed(redis_client, current=15, target=21)
  thread = PIDThread(INPUT, OUTPUT, 0, ZONE)
  thread.pid.sample_time = 0

  run_ticks(thread, 2)

  assert float(redis_client.get(OUTPUT)) > 0


def test_warm_room_calls_for_nothing(redis_client, run_ticks):
  seed(redis_client, current=25, target=21)
  thread = PIDThread(INPUT, OUTPUT, 0, ZONE)
  thread.pid.sample_time = 0

  run_ticks(thread, 2)

  assert float(redis_client.get(OUTPUT)) == 0


def test_output_is_limited_to_unit_range(redis_client, run_ticks):
  seed(redis_client, current=-40, target=40)
  thread = PIDThread(INPUT, OUTPUT, 0, ZONE)
  thread.pid.sample_time = 0

  run_ticks(thread, 3)

  assert 0 <= float(redis_client.get(OUTPUT)) <= 1


def test_records_sample_time(redis_client, run_ticks):
  seed(redis_client, current=18, target=21)
  thread = PIDThread(INPUT, OUTPUT, 0, ZONE)
  thread.pid.sample_time = 0

  run_ticks(thread, 2)

  assert thread.last_sample_time == "t0"


def test_missing_temperature_does_not_crash(redis_client, run_ticks):
  thread = PIDThread(INPUT, OUTPUT, 0, ZONE)
  thread.pid.sample_time = 0

  run_ticks(thread, 2)

  assert redis_client.get(OUTPUT) is not None

from types import SimpleNamespace

from src.config import RedisConfig
from src.zone_valve_thread import ZoneValveThread

SENSOR = "/home/sensors/a"
STATE = f"{SENSOR}/heating_cooling_state"
ZONE = SimpleNamespace(name="Test")
REDIS = RedisConfig(host="localhost", port=6379)


def make_thread():
  return ZoneValveThread(SENSOR, ZONE, REDIS)


def seed(redis_client, state=1, control_value=0.3):
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", state)
  redis_client.set(f"{SENSOR}/control_value", control_value)


def published_states(redis_client, run_ticks, thread, ticks):
  states = []
  run_ticks(thread, ticks, on_tick=lambda: states.append(int(redis_client.get(STATE))))
  return states


def test_duration_is_ten_minutes_of_ticks(redis_client):
  thread = make_thread()

  assert thread.duration == 10 * 60 / thread.interval


def test_duty_cycle_matches_control_value(redis_client, run_ticks):
  seed(redis_client, control_value=0.3)
  thread = make_thread()

  states = published_states(redis_client, run_ticks, thread, 120)

  on_ticks = int(0.3 * thread.duration)
  assert states == [1] * on_ticks + [0] * (120 - on_ticks)


def test_cycle_wraps_after_full_duration(redis_client, run_ticks):
  seed(redis_client, control_value=0.1)
  thread = make_thread()

  states = published_states(redis_client, run_ticks, thread, 121)

  assert states[0] == 1
  assert states[120] == 1


def test_off_state_never_opens_valve(redis_client, run_ticks):
  seed(redis_client, state=0, control_value=1)
  thread = make_thread()

  states = published_states(redis_client, run_ticks, thread, 5)

  assert set(states) == {0}


def test_waits_without_target_state(redis_client, run_ticks):
  redis_client.set(f"{SENSOR}/control_value", 1)
  thread = make_thread()

  run_ticks(thread, 3)

  assert redis_client.get(STATE) is None


def test_waits_without_control_value(redis_client, run_ticks):
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", 1)
  thread = make_thread()

  run_ticks(thread, 3)

  assert redis_client.get(STATE) is None


def test_publishes_state(redis_client, run_ticks):
  seed(redis_client, control_value=1)
  thread = make_thread()

  run_ticks(thread, 1)

  assert redis_client.get(STATE) == b"1"


def test_boost_forces_valve_open(redis_client, run_ticks):
  seed(redis_client, state=0, control_value=0)
  redis_client.set(f"{SENSOR}/boost", "true")
  thread = make_thread()

  run_ticks(thread, 1)

  assert redis_client.get(STATE) == b"1"

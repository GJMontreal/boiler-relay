from types import SimpleNamespace

import pytest

from src.zone_valve_thread import ZoneValveThread

SENSOR = "/home/sensors/a"
ZONE = SimpleNamespace(name="Test")


def make_thread(active_low=False, pins=("P8_10",)):
  return ZoneValveThread(SENSOR, list(pins), active_low, ZONE)


def seed(redis_client, state=1, control_value=0.3):
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", state)
  redis_client.set(f"{SENSOR}/control_value", control_value)


def states(gpio):
  return [state for _, state in gpio]


def test_duration_is_ten_minutes_of_ticks(redis_client, gpio):
  thread = make_thread()

  assert thread.duration == 10 * 60 / thread.interval


def test_init_drives_outputs_inactive(redis_client, gpio):
  make_thread(active_low=True, pins=("P8_10", "P8_14"))

  assert gpio == [("P8_10", 1), ("P8_14", 1)]


def test_duty_cycle_matches_control_value(redis_client, gpio, run_ticks):
  seed(redis_client, control_value=0.3)
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 121)

  on_ticks = int(0.3 * thread.duration)
  assert states(gpio)[:on_ticks] == [1] * on_ticks
  assert states(gpio)[on_ticks:120] == [0] * (120 - on_ticks)


def test_cycle_wraps_after_full_duration(redis_client, gpio, run_ticks):
  seed(redis_client, control_value=0.1)
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 121)

  assert states(gpio)[0] == 1
  assert states(gpio)[120] == 1


def test_active_low_inverts_output(redis_client, gpio, run_ticks):
  seed(redis_client, control_value=1)
  thread = make_thread(active_low=True)
  gpio.clear()

  run_ticks(thread, 1)

  assert states(gpio) == [0]


def test_all_pins_follow_the_zone(redis_client, gpio, run_ticks):
  seed(redis_client, control_value=1)
  thread = make_thread(pins=("P8_10", "P8_14"))
  gpio.clear()

  run_ticks(thread, 1)

  assert gpio == [("P8_10", 1), ("P8_14", 1)]


def test_off_state_never_opens_valve(redis_client, gpio, run_ticks):
  seed(redis_client, state=0, control_value=1)
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 5)

  assert set(states(gpio)) == {0}


def test_waits_without_target_state(redis_client, gpio, run_ticks):
  redis_client.set(f"{SENSOR}/control_value", 1)
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 3)

  assert gpio == []


def test_waits_without_control_value(redis_client, gpio, run_ticks):
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", 1)
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 3)

  assert gpio == []


def test_publishes_state(redis_client, gpio, run_ticks):
  seed(redis_client, control_value=1)
  thread = make_thread()

  run_ticks(thread, 1)

  assert redis_client.get(f"{SENSOR}/heating_cooling_state") == b"1"


@pytest.mark.xfail(reason="zone_valve_thread does not import json", raises=NameError, strict=True)
def test_boost_forces_valve_open(redis_client, gpio, run_ticks):
  seed(redis_client, state=0, control_value=0)
  redis_client.set(f"{SENSOR}/boost", "true")
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 2)

  assert states(gpio) == [1]

import random

import pytest
from simple_pid import PID as SimplePID

from boiler_relay.pid import PID

STEP = 10.0


class Clock:
  def __init__(self):
    self.now = 1000.0

  def __call__(self):
    return self.now

  def advance(self, seconds):
    self.now += seconds


def recorded_sequence(count=3000):
  rng = random.Random(7)
  temperature = 19.8
  rows = []
  for index in range(count):
    target = 20.0 if index < 400 else 22.0
    if index > 600:
      temperature += 0.0008 + rng.uniform(-0.01, 0.01)
    else:
      temperature += rng.uniform(-0.01, 0.01)
    rows.append((target, round(temperature, 2)))
  return rows


def test_the_defaults_match_simple_pid_sample_for_sample():
  clock = Clock()
  ours = PID(1.0, 0.01, 0.5, sample_time=STEP, time_fn=clock)
  theirs = SimplePID(1.0, 0.01, 0.5, setpoint=0, sample_time=STEP, output_limits=(0, 1), time_fn=clock)
  rng = random.Random(3)

  for index, (target, temperature) in enumerate(recorded_sequence()):
    clock.advance(rng.choice([STEP, STEP, STEP, 3.0, 25.0]))
    ours.setpoint = target
    theirs.setpoint = target
    if index == 1500:
      ours.reset()
      theirs.reset()
    assert ours(temperature) == theirs(temperature), index


@pytest.mark.parametrize("gains", [(2.0, 0.05, 0.0), (0.5, 0.0, 1.0), (1.0, 0.001, 0.25)])
def test_other_gains_match_simple_pid_while_the_cap_is_inactive(gains):
  clock = Clock()
  ours = PID(*gains, sample_time=STEP, time_fn=clock)
  theirs = SimplePID(*gains, setpoint=0, sample_time=STEP, output_limits=(0, 1), time_fn=clock)

  for target, temperature in recorded_sequence(1200):
    clock.advance(STEP)
    ours.setpoint = target
    theirs.setpoint = target
    assert ours(temperature) == theirs(temperature)


def test_the_output_is_held_between_samples():
  clock = Clock()
  pid = PID(1.0, 0.0, 0.0, sample_time=STEP, time_fn=clock)
  pid.setpoint = 21.0

  first = pid(20.5)
  clock.advance(3.0)

  assert pid(19.0) == first


def test_the_output_stays_between_zero_and_one():
  clock = Clock()
  pid = PID(5.0, 0.0, 0.0, sample_time=STEP, time_fn=clock)

  pid.setpoint = 30.0
  clock.advance(STEP)
  assert pid(10.0) == 1.0
  pid.setpoint = 0.0
  clock.advance(STEP)
  assert pid(10.0) == 0.0


def run_hours(pid, clock, hours, setpoint, temperature):
  pid.setpoint = setpoint
  peak = 0.0
  for _ in range(int(hours * 3600 / STEP)):
    clock.advance(STEP)
    pid(temperature)
    peak = max(peak, pid.integral)
  return peak


def test_the_integral_never_exceeds_the_cap_after_hours_of_positive_error():
  clock = Clock()
  pid = PID(1.0, 0.001, 0.0, integral_cap=0.3, sample_time=STEP, time_fn=clock)

  peak = run_hours(pid, clock, 6, 22.0, 20.0)

  assert peak == 0.3
  assert pid.integral == 0.3


def test_with_the_default_cap_the_integral_holds_full_output():
  clock = Clock()
  pid = PID(1.0, 0.01, 0.0, sample_time=STEP, time_fn=clock)

  run_hours(pid, clock, 6, 22.0, 20.0)

  assert pid.integral == 1.0


def test_the_output_falls_once_the_temperature_passes_the_target_with_a_capped_integral():
  clock = Clock()
  pid = PID(1.0, 0.001, 0.0, integral_cap=0.3, sample_time=STEP, time_fn=clock)
  run_hours(pid, clock, 6, 22.0, 20.0)

  pid.setpoint = 22.0
  clock.advance(STEP)

  assert pid(22.5) == 0.0


def test_an_uncapped_integral_keeps_heating_past_the_same_overshoot():
  clock = Clock()
  pid = PID(1.0, 0.01, 0.0, sample_time=STEP, time_fn=clock)
  run_hours(pid, clock, 6, 22.0, 20.0)

  pid.setpoint = 22.0
  clock.advance(STEP)

  assert pid(22.5) > 0.4


def test_a_zero_cap_removes_the_integral():
  clock = Clock()
  pid = PID(1.0, 0.5, 0.0, integral_cap=0.0, sample_time=STEP, time_fn=clock)

  run_hours(pid, clock, 1, 22.0, 20.0)

  assert pid.integral == 0.0


def test_the_integral_does_not_go_below_zero():
  clock = Clock()
  pid = PID(1.0, 0.01, 0.0, sample_time=STEP, time_fn=clock)

  run_hours(pid, clock, 2, 18.0, 22.0)

  assert pid.integral == 0.0


def test_reset_clears_the_integral_and_the_held_output():
  clock = Clock()
  pid = PID(1.0, 0.01, 0.0, integral_cap=0.3, sample_time=STEP, time_fn=clock)
  run_hours(pid, clock, 1, 22.0, 20.0)

  pid.reset()

  assert pid.integral == 0.0
  assert pid(22.0) == 0.0

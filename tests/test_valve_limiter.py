import logging

from boiler_relay.valve_limiter import ValveLimiter

DT = 5
MIN_ON = 300
MIN_OFF = 780


def limiter():
  return ValveLimiter("Bedrooms", MIN_ON, MIN_OFF)


def run(valve, demand, seconds, pending=0.0, calling=True, boost=False):
  opened = []
  for _ in range(int(seconds / DT)):
    opened.append(valve.step(demand, calling, DT, pending, boost))
  return opened


def seconds_open(opened):
  return sum(opened) * DT


def test_a_valve_starts_closed_with_no_wait_to_open():
  valve = limiter()

  assert run(valve, True, MIN_ON, pending=MIN_ON)[0] is True


def test_a_short_demand_is_held_back():
  valve = limiter()

  assert not any(run(valve, True, 120))
  assert not any(run(valve, False, 600))


def test_a_short_demand_accumulates_until_it_reaches_the_minimum_on_time():
  valve = limiter()
  opened = []
  for _ in range(5):
    opened += run(valve, True, 120)
    opened += run(valve, False, 480)

  assert seconds_open(opened) >= MIN_ON
  assert opened.index(True) * DT >= 2 * 600


def test_released_demand_keeps_the_valve_open_for_at_least_the_minimum_on_time():
  valve = limiter()
  run(valve, True, 120)
  run(valve, False, 480)
  run(valve, True, 120)
  run(valve, False, 480)
  opened = run(valve, True, 120)
  opened += run(valve, False, 30 * 60)

  assert seconds_open(opened) >= MIN_ON
  assert valve.open is False


def test_the_valve_delivers_the_demand_it_accumulated():
  valve = limiter()
  delivered = 0
  demanded = 0
  for window in range(12):
    demand_seconds = 100
    opened = run(valve, True, demand_seconds) + run(valve, False, 600 - demand_seconds)
    delivered += seconds_open(opened)
    demanded += demand_seconds

  assert abs(delivered - demanded) <= MIN_ON


def test_a_demand_that_will_last_the_minimum_opens_at_once():
  valve = limiter()

  opened = run(valve, True, 60, pending=MIN_ON)

  assert opened[0] is True


def test_the_valve_stays_open_for_the_minimum_on_time_after_the_demand_ends():
  valve = limiter()
  run(valve, True, 20, pending=MIN_ON)

  opened = run(valve, False, MIN_ON)

  assert all(opened[:55])
  assert opened[-1] is False


def test_the_off_time_blocks_a_reopen():
  valve = limiter()
  run(valve, True, MIN_ON, pending=MIN_ON)
  run(valve, False, 5)
  assert valve.open is False

  opened = run(valve, True, MIN_OFF - 10, pending=MIN_ON)

  assert not any(opened)
  assert any(run(valve, True, 30, pending=MIN_ON))


def test_the_off_time_counts_from_the_close_command():
  valve = limiter()
  run(valve, True, 200, pending=MIN_ON)
  run(valve, False, 400)
  closed_at = valve.age

  assert valve.open is False
  assert closed_at < MIN_OFF
  assert not any(run(valve, True, MIN_OFF - closed_at - 20, pending=MIN_ON))


def test_demand_that_arrives_during_the_off_time_waits_and_is_released():
  valve = limiter()
  run(valve, True, MIN_ON, pending=MIN_ON)
  run(valve, False, DT)
  opened = run(valve, True, MIN_OFF + 60, pending=MIN_ON)

  assert opened[-1] is True


def test_boost_bypasses_the_minimums():
  valve = limiter()
  run(valve, True, MIN_ON, pending=MIN_ON)
  run(valve, False, DT)

  assert all(run(valve, False, 60, boost=True))


def test_the_valve_closes_when_boost_ends_with_no_demand():
  valve = limiter()

  run(valve, False, DT, boost=True)

  assert run(valve, False, DT) == [False]


def test_boost_clears_the_accumulated_demand():
  valve = limiter()
  run(valve, True, 200)
  run(valve, False, DT, boost=True)

  assert valve.balance == 0.0


def test_losing_the_call_drops_the_accumulated_demand():
  valve = limiter()
  run(valve, True, 200)
  run(valve, False, DT, calling=False)

  assert valve.balance == 0.0
  assert not any(run(valve, True, 120))


def test_cut_drops_the_accumulated_demand_and_moves_the_clock():
  valve = limiter()
  run(valve, True, 100)

  valve.cut(MIN_OFF)

  assert valve.balance == 0.0
  assert valve.age >= MIN_OFF


def test_a_cut_closes_an_open_valve_before_its_minimum_on_time():
  valve = limiter()
  run(valve, True, 20, pending=MIN_ON)
  assert valve.open is True

  assert valve.step(False, False, DT, cut=True) is False
  assert valve.open is False
  assert valve.age == 0.0


def test_a_cut_starts_the_off_time_from_the_close():
  valve = limiter()
  run(valve, True, 20, pending=MIN_ON)
  valve.step(False, False, DT, cut=True)

  assert not any(run(valve, True, MIN_OFF - 20, pending=MIN_ON))
  assert any(run(valve, True, 40, pending=MIN_ON))


def test_a_cut_on_a_closed_valve_keeps_the_off_timer_running():
  valve = limiter()
  run(valve, True, 20, pending=MIN_ON)
  valve.step(False, False, DT, cut=True)
  run(valve, False, 100, calling=False)
  age = valve.age

  valve.step(False, False, DT, cut=True)

  assert valve.age == age + DT


def test_boost_wins_over_a_cut():
  valve = limiter()

  assert valve.step(False, False, DT, boost=True, cut=True) is True


def test_a_valve_can_start_as_just_closed():
  valve = ValveLimiter("Bedrooms", MIN_ON, MIN_OFF, closed_for=0.0)

  assert not any(run(valve, True, MIN_OFF - 10, pending=MIN_ON))
  assert any(run(valve, True, 20, pending=MIN_ON))


def test_a_cut_that_overrides_the_minimum_is_logged(caplog):
  valve = limiter()
  run(valve, True, 20, pending=MIN_ON)
  with caplog.at_level(logging.INFO):
    valve.step(False, False, DT, cut=True)

  assert any("before its minimum on time" in record.getMessage() for record in caplog.records)


def test_a_hold_is_logged_once(caplog):
  valve = limiter()
  with caplog.at_level(logging.INFO):
    run(valve, True, 200)

  assert [record.getMessage() for record in caplog.records if "accumulates" in record.getMessage()] == [
    "zone Bedrooms accumulates 5 of 300 seconds of demand"]


def test_an_accumulated_release_is_logged(caplog):
  valve = limiter()
  with caplog.at_level(logging.INFO):
    run(valve, True, 200)
    run(valve, False, 100)
    run(valve, True, 120)

  assert any("releases" in record.getMessage() for record in caplog.records)


def test_an_off_time_hold_is_logged_once(caplog):
  valve = limiter()
  run(valve, True, MIN_ON, pending=MIN_ON)
  run(valve, False, DT)
  with caplog.at_level(logging.INFO):
    run(valve, True, 120, pending=MIN_ON)

  assert len([record for record in caplog.records if "holds a call back" in record.getMessage()]) == 1

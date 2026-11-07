import logging

from boiler_relay import boiler_thread
from boiler_relay.boiler_thread import BoilerThread
from boiler_relay.config import BoilerConfig

INPUTS = ["P8_7", "P8_9", "P8_11"]


def make_thread(active_low=False, inputs=INPUTS, poll_interval=5):
  config = BoilerConfig(output_gpio="P8_18", active_low=active_low, poll_interval=poll_interval)
  return BoilerThread(config, inputs)


def outputs(gpio):
  return [state for pin, state in gpio if pin == "P8_18"]


def break_inputs(monkeypatch, state):
  def read(pin):
    if state["broken"]:
      raise OSError("pin unreadable")
    return 1

  monkeypatch.setattr(boiler_thread.GPIO, "input", staticmethod(read))


def test_init_drives_output_inactive(gpio):
  make_thread(active_low=True)

  assert outputs(gpio) == [1]


def test_polls_at_the_configured_interval(gpio):
  assert make_thread(poll_interval="10").interval == 10.0


def test_boiler_off_when_no_zone_calls(gpio, run_ticks):
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 1)

  assert outputs(gpio) == [0]


def test_any_input_turns_boiler_on(gpio, gpio_inputs, run_ticks):
  gpio_inputs["P8_11"] = 1
  thread = make_thread()
  gpio.clear()

  run_ticks(thread, 1)

  assert outputs(gpio) == [1]


def test_active_low_inverts_output(gpio, gpio_inputs, run_ticks):
  thread = make_thread(active_low=True)
  gpio.clear()

  run_ticks(thread, 1)
  gpio_inputs["P8_7"] = 1
  run_ticks(thread, 1)

  assert outputs(gpio) == [1, 0]


def test_follows_inputs_each_tick(gpio, gpio_inputs, run_ticks):
  thread = make_thread()
  gpio.clear()
  gpio_inputs["P8_9"] = 1

  run_ticks(thread, 1)
  gpio_inputs["P8_9"] = 0
  run_ticks(thread, 1)

  assert outputs(gpio) == [1, 0]


def test_no_inputs_leaves_boiler_off(gpio, run_ticks):
  thread = make_thread(inputs=[])
  gpio.clear()

  run_ticks(thread, 1)

  assert outputs(gpio) == [0]


def test_call_changes_are_logged_once(gpio, gpio_inputs, run_ticks, caplog):
  gpio_inputs["P8_9"] = 1
  thread = make_thread()

  with caplog.at_level(logging.INFO, logger="boiler_relay.boiler_thread"):
    run_ticks(thread, 3)

  assert caplog.text.count("boiler call None -> 1") == 1


def test_a_failed_poll_does_not_stop_the_loop(gpio, run_ticks, monkeypatch):
  state = {"broken": True}
  thread = make_thread()
  break_inputs(monkeypatch, state)
  gpio.clear()

  run_ticks(thread, 2)

  assert outputs(gpio) == []
  assert thread.failures == 2


def test_three_failed_polls_drive_the_boiler_inactive(gpio, run_ticks, monkeypatch, caplog):
  state = {"broken": True}
  thread = make_thread(active_low=True)
  break_inputs(monkeypatch, state)
  gpio.clear()

  with caplog.at_level(logging.ERROR, logger="boiler_relay.boiler_thread"):
    run_ticks(thread, 3)

  assert outputs(gpio) == [1]
  assert "pin unreadable" in caplog.text


def test_the_boiler_resumes_when_polls_succeed_again(gpio, run_ticks, monkeypatch, caplog):
  state = {"broken": True}
  thread = make_thread()
  break_inputs(monkeypatch, state)
  run_ticks(thread, 3)
  state["broken"] = False
  gpio.clear()

  with caplog.at_level(logging.INFO, logger="boiler_relay.boiler_thread"):
    run_ticks(thread, 1)

  assert outputs(gpio) == [1]
  assert thread.failures == 0
  assert "recovered after 3 failed polls" in caplog.text


def test_shutdown_drives_the_boiler_inactive(gpio):
  thread = make_thread(active_low=True)
  gpio.clear()

  thread.shutdown()

  assert thread.stopping.is_set()
  assert outputs(gpio) == [1]


def test_the_loop_exits_when_stopping_is_set(gpio, monkeypatch):
  thread = make_thread()
  monkeypatch.setattr(boiler_thread, "sleep", lambda _: thread.stopping.set())

  thread.run()

  assert thread.stopping.is_set()

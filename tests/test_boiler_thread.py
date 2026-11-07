from src.boiler_thread import BoilerThread
from src.config import BoilerConfig

INPUTS = ["P8_7", "P8_9", "P8_11"]


def make_thread(active_low=False, inputs=INPUTS):
  return BoilerThread(BoilerConfig(output_gpio="P8_18", active_low=active_low), inputs)


def outputs(gpio):
  return [state for pin, state in gpio if pin == "P8_18"]


def test_init_drives_output_inactive(gpio):
  make_thread(active_low=True)

  assert outputs(gpio) == [1]


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

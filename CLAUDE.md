# boiler-relay

Python control software for a zone-valve hydronic heating system on a BeagleBone. Each zone is one thread that runs a PID loop on a temperature from redis and drives its outputs. A boiler output follows the OR of the zone call-for-heat inputs.

## Branch state

`more_better_modular` is the development branch. It replaces the legacy flat scripts with the `boiler_relay` package. The legacy scripts are deleted, and `python -m boiler_relay` has not run end to end yet. The old code is in git history before `f6493e9`.

Known breakage in the new code:

- `boiler_relay/__main__.py` imports `unopt`, which is not in `requirements.txt`.
- `ZoneConfig` follows the `system_config.json` zone shape (`sensor_path`, `outputs`).
- `MQTTRelay` publishing has only run against a fake paho client, never a broker.
- `deploy.sh` and the unit template were rewritten for the package layout and have not been run against a device.

## Layout

- `boiler_relay/__main__.py`: entry point, run as `python -m boiler_relay`. Reads `--config` (default `config/system_config.json`, resolved from the project root), builds `Zone` objects and a `BoilerThread`, and starts them.
- `boiler_relay/zone.py`: `Zone` is a thread. Every `interval` seconds it reads temperature, setpoint, target state and boost from redis, runs the PID, turns the control value into a duty cycle over a ten minute window, writes `control_value` and `heating_cooling_state` to redis, calls `activate` on each output, and appends a CSV row when `LOG_PATH` exists. The PID samples every `pid_interval`.
- `boiler_relay/boiler_thread.py`: `BoilerThread`, turns the boiler output on when any pin in the top-level `inputs` list is high.
- `boiler_relay/outputs/`: one file per output type. `actuator.py` is the `Actuator` base class with `start`, `stop` and `activate(value)`. `gpio_output.py` is `GPIOOutput` (`type: gpio`, one `pin`). `mqtt_relay.py` is `MQTTRelay`, which keeps only the latest value and sends it from a worker thread so a slow broker never stalls the zone. `__init__.py` holds `create_output`. A new output type is a subclass with an `output_type` string, constructed as `(output_config, mqtt_config)`, imported in `__init__.py`.
- `boiler_relay/config.py`: dataclass configs with `from_file`.
- `boiler_relay/gpio.py`: exports `GPIO`. It is `Adafruit_BBIO.GPIO` when that imports, and a stub that prints otherwise. `gpio_output.py` and `boiler_thread.py` import it from here.
- `boiler_relay/heating_cooling_state.py`: the `HeatingCoolingState` enum.
- `config/system_config.json`: the config, with `mqtt`, `redis`, `zones`, `boiler` and `inputs`.
- `deploy.sh`, `deploy/`: copy the project to the device over ssh and build a virtualenv. `*.template` files hold `<user_name>` and `<project_name>` placeholders. The generated `setup_python.sh` and `boiler_relay.service` are gitignored.
- `docs/img/`: images for the README.

## Redis contract

The Homebridge plugin and the MQTT bridge share these keys. Do not rename them. Each zone has a `sensor_path` such as `/home/sensors/0xFD69`.

- `<sensor_path>/current_temperature`: JSON `{"value", "time"}`. Written by the MQTT bridge.
- `<sensor_path>/target_temperature`: JSON `{"value"}`. Written by Homebridge.
- `<sensor_path>/target_heatingcooling_state`: int, `HeatingCoolingState` (0 off, 1 heat, 2 cool).
- `<sensor_path>/control_value`: float 0 to 1, PID output. Written by the zone.
- `<sensor_path>/boost`: JSON boolean, forces the valve open.
- `<sensor_path>/heating_cooling_state`: set and published by the zone.

## Conventions

- Two-space indent in `__main__.py`, `config.py` and `outputs/`, four in `zone.py` and `boiler_thread.py`. Match the file you edit.
- One thread per zone, one per MQTT relay and one for the boiler. Loops are `while True` with a `sleep(interval)`. Outputs are called, not polled.
- A zone's `active_low` is the default for its gpio outputs. An output's own `active_low` overrides it. `GPIOOutput.activate` inverts at the last step before `GPIO.output`.
- GPIO pin names are BeagleBone headers such as `P8_10`.
- Tests live in `tests/` and use pytest with fakeredis and a recording GPIO. Run `.venv/bin/python -m pytest`. Loop threads are stopped by a fake `sleep` that raises, see `run_ticks` in `tests/conftest.py`.
- No linter. Run `python -m boiler_relay` to smoke test with the stub GPIO. It needs a local redis.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

`Adafruit-BBIO` fails to install off the BeagleBone. `requirements-dev.txt` leaves it out and lists the other dependencies itself.

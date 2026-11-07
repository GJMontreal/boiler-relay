# boiler-relay

Python control software for a zone-valve hydronic heating system on a BeagleBone. Each zone is one thread that runs a PID loop on a temperature from redis and drives its outputs. A boiler output follows the OR of the zone call-for-heat inputs.

## Branch state

`more_better_modular` is the development branch. It replaces the legacy flat scripts with `main.py` and `src/`. The legacy scripts are deleted, and `main.py` has not run end to end yet. The old code is in git history before `f6493e9`.

Known breakage in the new code:

- `main.py` imports `unopt`, which is not in `requirements.txt`.
- `ZoneConfig` follows the `system_config.json` zone shape (`sensor_path`, `outputs`). `config.json`, the `main.py` default, still uses the old `input_gpio` and `output_gpio` keys and fails to load.
- `MQTTRelay` publishing has only run against a fake paho client, never a broker.
- `deploy.sh` copies `src/*.py` but not `main.py`. The unit files still run the deleted `boiler_relay.py`.

## Layout

- `main.py`: new entry point. Reads `--config` (default `config.json`), builds `Zone` objects and a `BoilerThread`, and starts them.
- `src/zone.py`: `Zone` is a thread. Every `interval` seconds it reads temperature, setpoint, target state and boost from redis, runs the PID, turns the control value into a duty cycle over a ten minute window, writes `control_value` and `heating_cooling_state` to redis, calls `activate` on each output, and appends a CSV row when `LOG_PATH` exists. The PID samples every `pid_interval`.
- `src/boiler_thread.py`: `BoilerThread`, turns the boiler output on when any pin in the top-level `inputs` list is high.
- `src/actuator.py`: `Actuator` base class with `start`, `stop` and `activate(value)`, plus `GPIOOutput` (`type: gpio`, one `pin`), `MQTTRelay` and `create_output`. `Zone` builds one actuator per output and calls `activate` from its own thread. `MQTTRelay` keeps only the latest value and sends it from a worker thread, so a slow broker never stalls the zone. A new actuator type is a subclass with an `output_type` string, constructed as `(output_config, mqtt_config)`.
- `src/config.py`: dataclass configs with `from_file`.
- `src/gpio.py`: exports `GPIO`. It is `Adafruit_BBIO.GPIO` when that imports, and a stub that prints otherwise. `actuator.py` and `boiler_thread.py` import it from here.
- `config.json`: legacy zone and boiler config. `system_config.json`: the new config shape, with `mqtt`, `redis`, `zones`, `boiler` and `inputs`.
- `deploy.sh`, `deploy/`, `unit/`: rsync-style deploy to the device and systemd unit. `*.template` files hold `<user_name>` and `<project_name>` placeholders.

## Redis contract

The Homebridge plugin and the MQTT bridge share these keys. Do not rename them. Each zone has a `sensor_path` such as `/home/sensors/0xFD69`.

- `<sensor_path>/current_temperature`: JSON `{"value", "time"}`. Written by the MQTT bridge.
- `<sensor_path>/target_temperature`: JSON `{"value"}`. Written by Homebridge.
- `<sensor_path>/target_heatingcooling_state`: int, `HeatingCoolingState` (0 off, 1 heat, 2 cool).
- `<sensor_path>/control_value`: float 0 to 1, PID output. Written by the zone.
- `<sensor_path>/boost`: JSON boolean, forces the valve open.
- `<sensor_path>/heating_cooling_state`: set and published by the zone.

## Conventions

- Two-space indent in `main.py` and the newer `src/` files, four in older ones. Match the file you edit.
- One thread per zone, one per MQTT relay and one for the boiler. Loops are `while True` with a `sleep(interval)`. Outputs are called, not polled.
- A zone's `active_low` is the default for its gpio outputs. An output's own `active_low` overrides it. `GPIOOutput.activate` inverts at the last step before `GPIO.output`.
- GPIO pin names are BeagleBone headers such as `P8_10`.
- Tests live in `tests/` and use pytest with fakeredis and a recording GPIO. Run `.venv/bin/python -m pytest`. Loop threads are stopped by a fake `sleep` that raises, see `run_ticks` in `tests/conftest.py`.
- No linter. Run `python main.py -c system_config.json` to smoke test with the stub GPIO. It needs a local redis.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

`Adafruit-BBIO` fails to install off the BeagleBone. `requirements-dev.txt` leaves it out and lists the other dependencies itself.

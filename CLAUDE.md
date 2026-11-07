# boiler-relay

Python control software for a zone-valve hydronic heating system on a BeagleBone. Each zone runs a PID loop on a temperature from redis and drives zone valve relays. A boiler output follows the OR of the zone call-for-heat inputs.

## Branch state

`more_better_modular` is the development branch. It replaces the legacy flat scripts with `main.py` and `src/`. The legacy scripts are deleted, and `main.py` has not run end to end yet. The old code is in git history before `f6493e9`.

Known breakage in the new code:

- `main.py` imports `unopt`, which is not in `requirements.txt`. `paho-mqtt` is also missing.
- `ZoneConfig` follows the `system_config.json` zone shape (`sensor_path`, `outputs`). `config.json`, the `main.py` default, still uses the old `input_gpio` and `output_gpio` keys and fails to load.
- `src/actuator.py` `MQTTRelay` builds the message and prints it. It does not publish to MQTT yet.
- `src/gpio.py` is a stub that prints. Real GPIO needs `Adafruit_BBIO.GPIO`, which only installs on the BeagleBone.
- `deploy.sh` copies `src/*.py` but not `main.py`. The unit files still run the deleted `boiler_relay.py`.

## Layout

- `main.py`: new entry point. Reads `--config` (default `config.json`), builds `Zone` objects and a `BoilerThread`, and starts them.
- `src/zone.py`: one zone. Owns a `PIDThread`.
- `src/output_thread.py`: `PIDThread` (reads temperature and setpoint from redis, writes `output_path`), `ZoneLoggingThread`.
- `src/boiler_thread.py`: `BoilerThread`, turns the boiler output on when any pin in the top-level `inputs` list is high.
- `src/zone_valve_thread.py`: turns `control_value` into a time-proportioned on/off cycle on the zone GPIOs.
- `src/actuator.py`: `Actuator` base class that polls redis `<path>/heating_cooling_state`, plus `MQTTRelay` and `create_output`. `Zone` builds one actuator per non-gpio output through `create_output`. A new actuator type is a subclass constructed as `(path, redis_config, mqtt_config, output_config)`.
- `src/config.py`: dataclass configs with `from_file`.
- `src/gpio.py`: GPIO wrapper for development off the BeagleBone.
- `config.json`: legacy zone and boiler config. `system_config.json`: the new config shape, with `mqtt`, `redis`, `zones`, `boiler` and `inputs`.
- `deploy.sh`, `deploy/`, `unit/`: rsync-style deploy to the device and systemd unit. `*.template` files hold `<user_name>` and `<project_name>` placeholders.

## Redis contract

The Homebridge plugin and the MQTT bridge share these keys. Do not rename them. Each zone has a `sensor_path` such as `/home/sensors/0xFD69`.

- `<sensor_path>/current_temperature`: JSON `{"value", "time"}`. Written by the MQTT bridge.
- `<sensor_path>/target_temperature`: JSON `{"value"}`. Written by Homebridge.
- `<sensor_path>/target_heatingcooling_state`: int, `HeatingCoolingState` (0 off, 1 heat, 2 cool).
- `<sensor_path>/control_value`: float 0 to 1, PID output.
- `<sensor_path>/boost`: JSON boolean, forces the valve open.
- `<sensor_path>/heating_cooling_state`: set and published by the zone valve thread.

## Conventions

- Two-space indent in `main.py` and the newer `src/` files, four in older ones. Match the file you edit.
- One thread per concern, each with a `while True` loop and a `sleep(interval)`.
- Outputs can be active low per zone. Invert at the last step before `GPIO.output`.
- GPIO pin names are BeagleBone headers such as `P8_10`.
- Tests live in `tests/` and use pytest with fakeredis and a recording GPIO. Run `.venv/bin/python -m pytest`. Loop threads are stopped by a fake `sleep` that raises, see `run_ticks` in `tests/conftest.py`.
- No linter. Run `python main.py -c system_config.json` to smoke test with the stub GPIO. It needs a local redis.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

`Adafruit-BBIO` fails to install off the BeagleBone. `requirements-dev.txt` leaves it out for that reason.

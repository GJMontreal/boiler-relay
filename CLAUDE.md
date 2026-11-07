# boiler-relay

Python control software for a zone-valve hydronic heating system on a BeagleBone. Each zone is one thread that runs a PID loop on a temperature from redis and drives its outputs. The boiler output follows the OR of the end-switch pins on the zone valves.

## Branch state

`more_better_modular` is the development branch. It replaces the legacy flat scripts with the `boiler_relay` package. The legacy scripts are deleted, and `python -m boiler_relay` has not run end to end yet. The legacy scripts are still on `develop` and `main`, and in this branch's history up to `14882aa`. The device runs them today as `boiler_relay.service`.

Known breakage in the new code:

- `MQTTRelay` publishing has only run against a fake paho client, never a broker.
- `deploy.sh` and the unit template were rewritten for the package layout and have not been run against a device.
- The device runs Python 3.7.3. The code parses there, but `paho-mqtt` 2.x and `simple-pid` have not been installed on it.

## Layout

- `boiler_relay/__main__.py`: entry point, run as `python -m boiler_relay`. Reads `--config` (default `config/system_config.json`, resolved from the project root), builds the zones and the boiler, starts them, and exits non-zero if any thread stops. `SIGTERM` stops everything and drives the outputs inactive. Invalid config exits 2.
- `boiler_relay/zone.py`: `Zone` is a thread. Every 5 seconds it reads temperature, setpoint, target state and boost from redis, runs the PID, turns the control value into a duty cycle over a `control_interval` minute window, writes `control_value` and `heating_cooling_state` to redis, and calls `activate` on each output. The PID samples every `pid_interval`. `COOL` and unknown target states are off. A reading whose sample time has not changed for two hours calls for no heat. Three failed ticks in a row drive the outputs inactive, and the zone keeps retrying.
- `boiler_relay/boiler_thread.py`: `BoilerThread`, turns the boiler output on when any end-switch pin is high. The pins come from the `end_switch` key on each zone's gpio outputs. Three failed polls in a row drive the boiler inactive.
- `boiler_relay/outputs/`: one file per output type. `actuator.py` is the `Actuator` base class with `start`, `stop` and `activate(value)`. `gpio_output.py` is `GPIOOutput` (`type: gpio`, one `pin`, optional `end_switch`). `mqtt_relay.py` is `MQTTRelay`, which keeps only the latest value and sends it from a worker thread so a slow broker never stalls the zone. `__init__.py` holds `create_output`. A new output type is a subclass with an `output_type` string, constructed as `(output_config, mqtt_config)`, imported in `__init__.py`. `create_output` raises `ValueError` for a missing or unsupported type, and an `MQTTRelay` raises without an `mqtt` section.
- `boiler_relay/config.py`: dataclass configs. `SystemConfig.from_file` parses the whole file and raises `ConfigError` for a missing section, an unknown key, mixed output types in a zone, `active_low` on an output, duplicate zone names or sensor paths, or a GPIO pin used twice.
- `boiler_relay/gpio.py`: exports `GPIO`. It is `Adafruit_BBIO.GPIO` when that imports, and a stub that logs otherwise. `gpio_output.py` and `boiler_thread.py` import it from here.
- `boiler_relay/heating_cooling_state.py`: the `HeatingCoolingState` enum.
- `config/system_config.json`: the config, with `mqtt` (optional), `redis`, `zones` and `boiler`. Sensor paths are the friendly names the legacy system uses. A zone is one sensor, one PID and one kind of output. Optional zone keys are `control_interval` (duty window in minutes, default 10), `active_low` and `pid` (`kp`, `ki`, `kd`).
- `deploy.sh`, `deploy/`: sync the project to the device with `rsync --delete` and build a virtualenv. `*.template` files hold `<service_name>` and `<service_user>` placeholders. The service is `boiler_relay_v2`, installed in `/var/lib/boiler_relay_v2` with the virtualenv in `.venv`, which the sync keeps. It runs as `SERVICE_USER`, default `heating`, which the caller creates. `deploy.sh` refuses `/var/lib/boiler_relay` and `/home/debian/boiler-relay`, the legacy service's locations. The generated `setup_python.sh`, `boiler_relay_v2.service` and `boiler_relay_v2_shadow.service` are gitignored.
  - `boiler_relay_v2.service` conflicts with `boiler_relay.service` and the shadow unit.
  - `boiler_relay_v2_shadow.service` conflicts with v2 only and has no `[Install]` section, so it never starts at boot. It runs `python -m boiler_relay --shadow`, and it cannot start until that flag exists.
  - `deploy/boiler_relay.service.d/conflicts.conf` is the legacy unit's drop-in. It makes legacy conflict with v2. `deploy.sh` prints the command that installs the units and the drop-in on the device.
  - `deploy/switch.sh <user> <host> legacy|v2|shadow` runs over `ssh -t` with sudo. It stops the old services and waits until they are inactive. It starts the new ones and moves the boot-time enable only after they stay up. `shadow` starts legacy and the shadow unit, because stopping v2 alone would leave the boiler uncontrolled. It never touches `mqtt_bridge.service`.
- `docs/img/`: images for the README.

## Redis contract

The Homebridge plugin and the MQTT bridge share these keys. Do not rename them. Each zone has a `sensor_path` such as `/home/sensors/kitchen`.

- `<sensor_path>/current_temperature`: JSON `{"value", "time"}`. Written by the MQTT bridge.
- `<sensor_path>/target_temperature`: JSON `{"value"}`. Written by Homebridge.
- `<sensor_path>/target_heatingcooling_state`: int, `HeatingCoolingState`. 0 is off and 1 is heat. Anything else is treated as off.
- `<sensor_path>/control_value`: float 0 to 1, PID output. Written by the zone.
- `<sensor_path>/boost`: JSON boolean, forces the valve open.
- `<sensor_path>/heating_cooling_state`: set and published by the zone.

## Conventions

- Two-space indent in `__main__.py`, `config.py` and `outputs/`, four in `zone.py` and `boiler_thread.py`. Match the file you edit.
- One thread per zone, one per MQTT relay and one for the boiler. Loops run until `stopping` is set, with a `sleep(interval)` outside the `try`. Outputs are called, not polled.
- Log with `logging`. INFO is for state changes, window summaries and warnings. Per-tick detail is DEBUG. Warn once per condition, not once per tick.
- `active_low` is set per zone and applies to its gpio outputs. `GPIOOutput.activate` inverts at the last step before `GPIO.output`.
- GPIO pin names are BeagleBone headers such as `P8_10`.
- Tests live in `tests/` and use pytest with fakeredis and a recording GPIO. Run `.venv/bin/python -m pytest`. Loop threads are stopped by a fake `sleep` that raises, see `run_ticks` in `tests/conftest.py`.
- No linter. Run `python -m boiler_relay` to smoke test with the stub GPIO. It needs a local redis.
- CI runs `pytest` on Python 3.7 and 3.11 (`.github/workflows/test.yml`). It has not run yet.

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
```

`Adafruit-BBIO` fails to install off the BeagleBone. `requirements-dev.txt` leaves it out and lists the other dependencies itself.

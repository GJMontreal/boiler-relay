The philosophy guiding this project and its documentation is straightforward: get it working then make improvements as needed. Perfection is the enemy of progress.

# Plumbing

Overall the heating system is quite simple. A boiler is connected via a manifold with zone valves to a series of radiators. When a zone calls for heat, first the zone valve opens, and when that is complete, the boiler and pump are then turned on.

![plumbing overview](./docs/img/plumbing_overview.jpeg)
Manifold with zone valves
![manifold](./docs/img/manifold.jpeg)

# Electronics
A beaglebone SBC running debian hosts all the software pieces as well as interfacing via GPIO to a relay board. The relays control the zone valves as well as the boiler

![electronics overview](./docs/img/electronics_overview.jpeg)
Beaglebone and relay board
![electronics](docs/img/electronics.jpeg)
# Software
This project contains the logic for zone and boiler control. Sensor data is sent to an MQTT broker (mosquitto in this case). A simple bridge written in python publishes these values to redis. The homebridge plugin reads and writes respective values to redis. This project reads those values and toggles the physical gpios.
The bits circled in red are the ones I've written. The UI is implemented as a [Homebridge plugin](https://github.com/GJMontreal/heating) 

![software overview](docs/img/software_overview.jpeg)
![software](docs/img/ui.jpeg)

## Two heating systems
Every zone belongs to one of two systems. The `system` field in the config says which.

- **Hydronic** is the boiler, the pump and the zone valves, driven from the BeagleBone's GPIO. Each valve has an end switch that closes when the valve is open. The boiler thread turns the boiler on when any end switch is closed. This is the only system with feedback, because the end switch confirms the valve moved.
- **Electric** is the Stairwell radiator behind a Zigbee relay, driven over MQTT. It has no end switch and no state feedback. The zone sends a power value and never learns whether the relay switched. An electric zone never calls the boiler, and the config refuses an `end_switch` on it.

## How a zone works
Each zone has a temperature sensor, a setpoint and one or more outputs. One thread per zone does the work.

1. A PID loop compares the current temperature to the setpoint and produces a control value between 0 and 1.
2. The zone turns that value into a duty cycle over a ten minute window. A control value of 0.3 opens the valve for three minutes of each ten. It publishes the result as the zone's `heating_cooling_state`.
3. The zone then calls each of its outputs with that state. An output is a local GPIO pin or an MQTT relay. MQTT messages go out on a separate thread, so a slow broker never delays the zone.
4. For hydronic zones, the boiler thread reads the end switch on each zone valve. It turns the boiler and pump on when any valve is open.

A boost flag in redis forces a zone open regardless of the PID output. Gpio outputs can be configured active low per zone.

If a reading stops changing for two hours, the zone calls for no heat until a new one arrives. A tick that fails, because redis is down for example, is retried. After three failures in a row the zone switches its outputs off.

## Redis keys
Every zone is identified by a sensor path such as `/home/sensors/kitchen`.

| Key | Written by | Value |
| --- | --- | --- |
| `<sensor_path>/current_temperature` | MQTT bridge | JSON with `value` and `time` |
| `<sensor_path>/target_temperature` | Homebridge | JSON with `value` |
| `<sensor_path>/target_heatingcooling_state` | Homebridge | 0 off, 1 heat. Anything else counts as off |
| `<sensor_path>/control_value` | zone | 0 to 1 |
| `<sensor_path>/boost` | Homebridge | JSON boolean |
| `<sensor_path>/heating_cooling_state` | zone | 0 or 1 |

Each service also publishes its decisions as JSON with a `time` field. `<mode>` is `active` for the running service and `shadow` for the shadow service.

| Key | Written by | Value |
| --- | --- | --- |
| `heating/<mode>/zones/<zone name>` | zone | `system`, `control_value`, `state` (0, 1 or null before the zone has a target state) and `time` |
| `heating/<mode>/hydronic/boiler` | boiler thread | `call` (0 or 1) and `time`. The shadow service derives the call from its zones' decisions, because it reads no pin |
| `heating/<mode>/heartbeat` | boiler thread | `time`, once per poll |

The read-only API and web interface live in the `heating-web` repo. It is deployed and versioned apart from this service, and it reads these keys. It also reads this project's `config/system_config.json` for each zone's name, sensor path and system.

## Configuration
Zones, the boiler output and the redis and MQTT endpoints are described in JSON. `config/system_config.json` is the default config file. A zone is one sensor, one PID and one kind of output: local GPIO pins or an MQTT relay. Each zone names its `system`, `hydronic` or `electric`. A gpio output on a hydronic zone may name an `end_switch` pin, and the boiler follows all of them. The config needs at least one hydronic zone with an `end_switch`. A zone can also set `control_interval` (the duty window in minutes) and `pid` gains. The program refuses to start on a config it cannot use, and says why.

The end switch pairing is verified on the device for all five valves, by boost tests read through sysfs on 2026-11-07.

- **Common and Kitchen** were swapped in the old config. Common's valve (`P8_8`) reports on `P8_15` and Kitchen's valve (`P8_16`) reports on `P8_7`, so the config pairs them that way.
- **Bedrooms** (`P8_10` with `P8_9`, `P8_14` with `P8_17`) match the config. Both switches rose with both outputs on, at 19:53 local. The test cannot say which switch belongs to which output, and the boiler follows both. `P8_17` needs its internal pull disabled. It powers on with a pulldown and reads low until it is set to gpio mode.
- **Study** (`P8_12` with `P8_11`) matches the config. `P8_11` rose about 3.5 minutes after the boost and fell about 3 minutes after the close.
- **BackRoom** (`P8_28` with `P8_27`) matches the config. `P8_27` rose about 3.5 minutes after the boost.

The service sets every end switch input to gpio mode with the pull disabled when it starts, so no input relies on its power-on state.

The BackRoom end switch is faulty. After the control loop turned the output off at 16:39:51 local on 2026-11-07, `P8_27` stayed high for about 10 minutes, until the actuator was pushed by hand. Until the switch is replaced, a BackRoom call can leave `P8_27` high and keep the boiler on with no demand.

## Status
The `more_better_modular` branch is the development branch. It replaced the original scripts with the `boiler_relay` package. `deploy.sh`, `deploy/switch.sh` and the systemd units have been written for it and have not been run against the device.

## Running
```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m boiler_relay
```
A local redis is required. `boiler_relay/gpio.py` uses `Adafruit_BBIO` when it is installed. Without it, a stub switches nothing and a warning is logged at startup.

## Versions
`boiler_relay/version.py` holds the version in `__version__`. Each service has its own semantic version, and each release is a `vX.Y.Z` git tag. `python -m boiler_relay --version` prints `boiler_relay <version> (<commit>)`. The commit comes from `build_info.json`, which `deploy.sh` writes next to the package. It is the short commit hash, with `-dirty` added when the working tree has changes. The commit reads `unknown` when the file is missing.

At startup the service sets `heating/versions/boiler-relay` to JSON with `version`, `commit` and the start `time`. It does this in active and shadow mode alike, and the key name does not include the mode. If redis is down at startup, it logs a warning and keeps running without the key.

## Deploying
`./deploy.sh <user> <host>` fills in the unit and setup templates from `deploy/`, syncs the package, config and `build_info.json` with `rsync --delete` and builds a virtualenv on the device. The service is `boiler_relay_v2`. It installs to `/var/lib/boiler_relay_v2` and runs as `SERVICE_USER` (default `heating`, created by the caller and a member of `gpio`). `.venv` survives the sync. The script refuses `/var/lib/boiler_relay` and `/home/debian/boiler-relay`, which belong to the legacy service.

The virtualenv build and every pip install run under `nice -n 19 ionice -c3`, so they cannot starve the live service on the single core.

The script prints the command that copies the units to `/etc/systemd/system` and installs the legacy drop-in. The drop-in, `deploy/boiler_relay.service.d/conflicts.conf`, makes `boiler_relay.service` conflict with v2.

`deploy/switch.sh <user> <host> legacy|v2|shadow [--confirm]` runs over `ssh -t` with sudo. It stops the old services, waits until they are inactive, starts the new ones and moves the boot-time enable. It changes nothing if the target unit is missing or does not stay up.

- `legacy` runs `boiler_relay` and enables it at boot.
- `v2` runs `boiler_relay_v2` and enables it at boot. Starting it stops the legacy service at once, so the script prints the running services it will stop and refuses to go on without `--confirm`.
- `shadow` keeps `boiler_relay` in control and adds `boiler_relay_v2_shadow`. It enables both at boot and disables `boiler_relay_v2`.
- `legacy` and `v2` disable the shadow at boot.

`boiler_relay_v2_shadow.service` runs `python -m boiler_relay --shadow`. Neither it nor `boiler_relay_v2` lists the other in `Conflicts=`, so starting one never stops the other. The shadow drives no GPIO and sends no MQTT, so it is safe beside v2. It starts at boot once enabled, after `redis-server` and `mosquitto`. `deploy.sh` prints `sudo systemctl enable boiler_relay_v2_shadow`, which enables only the shadow and never starts or enables `boiler_relay_v2`. The deploy installs and starts nothing itself. Shadow mode reads the same sensor keys and makes the same decisions, but it drives no GPIO, sends no MQTT and writes only under `heating/shadow/`. The active service publishes the same keys under `heating/active/`.

The scripts never touch `mqtt_bridge.service`. The bridge lives in `GJMontreal/mqtt-bridge`, and the legacy, v2 and shadow services and Homebridge all read what it writes.

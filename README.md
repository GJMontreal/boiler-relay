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

## How a zone works
Each zone has a temperature sensor, a setpoint and one or more outputs. One thread per zone does the work.

1. A PID loop compares the current temperature to the setpoint and produces a control value between 0 and 1.
2. The zone turns that value into a duty cycle over a ten minute window. A control value of 0.3 opens the valve for three minutes of each ten. It publishes the result as the zone's `heating_cooling_state`.
3. The zone then calls each of its outputs with that state. An output is a local GPIO pin or an MQTT relay. MQTT messages go out on a separate thread, so a slow broker never delays the zone.
4. The boiler thread reads the end switch on each zone valve. It turns the boiler and pump on when any valve is open.

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

## Configuration
Zones, the boiler output and the redis and MQTT endpoints are described in JSON. `config/system_config.json` is the default config file. A zone is one sensor, one PID and one kind of output: local GPIO pins or an MQTT relay. A gpio output may name an `end_switch` pin, and the boiler follows all of them. A zone can also set `control_interval` (the duty window in minutes) and `pid` gains. The program refuses to start on a config it cannot use, and says why.

## Status
The `more_better_modular` branch is the development branch. It replaced the original scripts with the `boiler_relay` package. `deploy.sh` and the systemd unit have been updated for it and still need a trial run on the device.

## Running
```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m boiler_relay
```
A local redis is required. `boiler_relay/gpio.py` uses `Adafruit_BBIO` when it is installed. Without it, a stub switches nothing and a warning is logged at startup.

## Deploying
`./deploy.sh <user> <host>` fills in the unit and setup templates from `deploy/`, copies the package and config over ssh and builds a virtualenv on the device. It installs to `/var/lib/boiler_relay` and the unit runs as the `heating` user. It deletes the existing install directory first.


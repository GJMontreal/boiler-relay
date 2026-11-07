# TODO

## Get `main.py` running

- [ ] Add `paho-mqtt` and the package providing `unopt` to `requirements.txt`, or drop `unopt`.
- [ ] Make `system_config.json` the `main.py` default and delete `config.json`.

## Outputs

- [ ] Finish `MQTTRelay`: publish the message to the topic over MQTT.
- [ ] Add a GPIO actuator so `type: gpio` outputs work.
- [ ] Move active-low handling to the output, per zone.

## Cleanup

- [ ] Remove the duplicate `PIDThread.write_row` or `Zone.write_row`.
- [ ] Remove `HeatingCoolingState` from `src/output_thread.py`, use `src/heating_cooling_state.py`.
- [ ] Move the log path out of code and into config.
- [ ] Move PID gains into per-zone config.

## Deploy

- [ ] Make `deploy.sh` copy `main.py` and the config.
- [ ] Point `unit/boiler_relay.service.template` and the unit at `main.py`. They still run the deleted `boiler_relay.py`.
- [ ] Take the install path from `setup_python.sh.template` instead of the hardcoded `/home/heating`.
- [ ] Replace `rm -rf` of the install directory with a safer sync.
- [ ] Remove generated `deploy/setup_python.sh` and `unit/boiler_relay.service` from git, keep the templates.

## Quality

- [ ] Add tests for `main.py` config loading.
- [ ] Replace `print` with `logging`.
- [ ] Add a clean shutdown path for the threads and GPIO cleanup.
- [ ] Update `.vscode/launch.json`, which still launches the `output_thread` module.

# TODO

## Get `main.py` running

- [ ] Add the package providing `unopt` to `requirements.txt`, or drop `unopt`.
- [ ] Make `system_config.json` the `main.py` default and delete `config.json`.

## Outputs

- [ ] Publish a real MQTT message from `MQTTRelay` against a broker and check the Zigbee relay switches.

## Cleanup

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
- [ ] Keep the zone loop alive when redis raises, and drive outputs inactive if it stops.
- [ ] Add a clean shutdown path for the threads and GPIO cleanup.
- [ ] Update `.vscode/launch.json`, which still launches the deleted `output_thread` module.

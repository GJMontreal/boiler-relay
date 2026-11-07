# TODO

## Get `python -m boiler_relay` running

- [ ] Add the package providing `unopt` to `requirements.txt`, or drop `unopt`.

## Outputs

- [ ] Publish a real MQTT message from `MQTTRelay` against a broker and check the Zigbee relay switches.

## Cleanup

- [ ] Move the log path out of code and into config.
- [ ] Move PID gains into per-zone config.

## Deploy

- [ ] Run the new `deploy.sh` and unit against the device. Both were rewritten for the package layout.
- [ ] Take the install path from `setup_python.sh.template` instead of the hardcoded `/home/heating`.
- [ ] Replace `rm -rf` of the install directory with a safer sync.

## Quality

- [ ] Add tests for config loading in `__main__.py`.
- [ ] Replace `print` with `logging`.
- [ ] Keep the zone loop alive when redis raises, and drive outputs inactive if it stops.
- [ ] Add a clean shutdown path for the threads and GPIO cleanup.

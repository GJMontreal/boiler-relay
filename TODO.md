# TODO

## Get `main.py` running

- [ ] Add `paho-mqtt` and the package providing `unopt` to `requirements.txt`, or drop `unopt`.
- [ ] Settle one zone config shape and make `ZoneConfig` in `src/config.py` match it.
- [ ] Import `json` in `src/zone_valve_thread.py`.
- [ ] Create a `ZoneValveThread` in `Zone` and start it.
- [ ] Fix `Zone.write_row`: define `os`, `LOG_PATH` and the valve thread it uses.
- [ ] Port `BoilerThread` into the new startup path.
- [ ] Pass `RedisConfig` into the threads instead of hardcoding `localhost:6379`.

## Outputs

- [ ] Wire `create_output` into zone setup so each zone builds its list of outputs.
- [ ] Give `Actuator` subclasses one constructor shape that `create_output` can call.
- [ ] Finish `MQTTRelay`: set `device_name`, publish the message to the topic.
- [ ] Add a GPIO actuator so `type: gpio` outputs work.
- [ ] Move active-low handling to the output, per zone.

## Cleanup

- [ ] Delete `boiler_relay.py` and root `output_thread.py` once `main.py` has parity.
- [ ] Remove the duplicate `PIDThread.write_row` or `Zone.write_row`.
- [ ] Remove `HeatingCoolingState` from `src/output_thread.py`, use `src/heating_cooling_state.py`.
- [ ] Delete `dump.rdb` and add it to `.gitignore`.
- [ ] Drop the unused config files once the shape is settled: `zones.json`, `mqtt.json`, `redis.json`, `message.json`, `system_config.json` or `config.json`.
- [ ] Move the log path out of code and into config.
- [ ] Move PID gains into per-zone config.

## Deploy

- [ ] Make `deploy.sh` copy `main.py` and the config.
- [ ] Point `unit/boiler_relay.service` at `main.py` when parity lands.
- [ ] Take the install path from `setup_python.sh.template` instead of the hardcoded `/home/heating`.
- [ ] Replace `rm -rf` of the install directory with a safer sync.
- [ ] Remove generated `deploy/setup_python.sh` and `unit/boiler_relay.service` from git, keep the templates.

## Quality

- [ ] Add tests for `Zone`, `BoilerThread`, `MQTTRelay` and `main.py` config loading.
- [ ] Remove the `xfail` on the boost test once `zone_valve_thread` imports `json`.
- [ ] Replace `print` with `logging`.
- [ ] Add a clean shutdown path for the threads and GPIO cleanup.
- [ ] Update `.vscode/launch.json`, which still launches the `output_thread` module.

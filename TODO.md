# TODO

Build order is fixed: hardening and config (done), deploy and shadow. The API and web interface now live in the heating-web repo, with their own TODO.md.

The project controls two systems, set per zone by the `system` field. Hydronic is the boiler, pump and zone valves on GPIO, with an end switch on each valve. Electric is the Stairwell radiator behind a Zigbee relay over MQTT, with no end switch. The relay reports its own power state. Published state lives under `heating/<mode>/`: `zones/<zone name>` carries the zone's `system`, and `hydronic/boiler` carries the boiler call.

## Step 2: deploy, switch and shadow

- [x] Add `--shadow` to `python -m boiler_relay`. Read the same sensor keys, compute the same decisions, touch no GPIO, send no MQTT, and write only under `heating/shadow/`.
- [x] Publish zone, boiler and heartbeat state under `heating/<mode>/` from the active service as well. Keep writing the Homebridge keys from the active service.
- [x] Rename the new service `boiler_relay_v2`, installed in `/var/lib/boiler_relay_v2`, running as `heating` through a `<service_user>` placeholder.
- [x] Add `boiler_relay_v2_shadow.service`. It has no `Conflicts=`, and v2 does not list it, so the two can run together.
- [x] Add `Conflicts=boiler_relay.service` to the v2 unit and a drop-in file for the legacy unit.
- [x] Keep `switch.sh` away from `mqtt_bridge.service`. The legacy, v2 and shadow services and Homebridge all read what the bridge writes. Note in the deploy docs that the bridge lives in `GJMontreal/mqtt-bridge`.
- [x] Start the shadow at boot: an `[Install]` section on the unit, an enable command printed by `deploy.sh`, and `switch.sh` enabling the shadow only for `shadow`.
- [ ] Install the new shadow unit on the device, run `sudo systemctl enable boiler_relay_v2_shadow` and reboot to check it starts.
- [x] Add `deploy/switch.sh legacy|v2|shadow`. It stops the old service, waits, starts the new one and moves the boot-time enable. It runs over `ssh -t` with sudo.
- [x] Rewrite `deploy.sh` to use `rsync --delete` with `.venv` excluded, to derive paths from the service name, and to refuse the legacy directory.
- [x] Move `After=redis.service` from `[Service]` to `[Unit]` in the unit template.
- [x] First deploy at the house during heating season. Watch each zone open and close once and check the boiler follows the end switches. Roll back with `switch.sh legacy`.
- [x] Install `paho-mqtt` 2.x, `simple-pid` and `redis==3.5.3` on the device's Python 3.7 in the new venv.
- [x] Add a per-zone `pid` block with an integral cap, our own PID class, a shadow-only profile and the profile published in each zone's state, so the shadow can run candidate gains.
- [x] Harden the v2 and shadow units for boot: order after `redis-server` and `mosquitto`, restart after 5 seconds and never hit the start limit. `switch.sh v2` leaves the shadow running.
- [x] Add a top-level `pid` default so the live gains are set once, with the zone block, then the top-level block, then the built-in values.
- [ ] Compare the shadow's candidate gains with the legacy controller on the Compare page over a few heating cycles, then decide the gains for v2.
- [ ] Replace the BackRoom end switch (`P8_27`). It stayed high for about 10 minutes after the output turned off on 2026-11-07, and a BackRoom call can keep the boiler on with no demand until then.

## Backlog

- [x] Accept an optional top-level `site_name` in the config for the web interface title. The controller validates it and ignores it. The real name stays in a device-only file.
- [ ] Boiler short-cycling protection (a minimum on and off time). Deferred until the problem shows.
- [ ] Check on the device that the relay confirmation works: the subscription, the `confirmed` fields, the silence retries and the refresh. The relay reported every repeated command at the 5 second cadence on 2026-11-08, 17 of 17. Watch one 60 second refresh on the device and check that `confirmed_silent` stays false. The code has only run against a fake client.
- [ ] Publish a real MQTT message from `MQTTRelay` with the real topic and device and check the Zigbee relay switches. Publishing to a broker already passes.
- [ ] Revisit sending relay commands through redis and the bridge, which would drop paho from the control process. Not now, because the radiator would then depend on the bridge to switch.
- [ ] Homebridge needs a stairwell thermostat that writes `/home/sensors/stairwell/target_temperature` and `target_heatingcooling_state`. Until it does, the Stairwell zone idles.
- [x] Confirm the Bedrooms end-switch pairing: `P8_10` with `P8_9` and `P8_14` with `P8_17`.
- [ ] Review the device's login credentials and remote access.
- [ ] The `back_room` sensor stopped reporting on 2026-10-24. Check its battery.
- [x] Set every end-switch input to gpio mode with the pull disabled, so no pin relies on its power-on state.
- [x] Check on the device that the service user can write the pinmux state files, or that `GPIO.setup` on an end-switch input succeeds at startup.
- [ ] Move PID gains per zone only if the stairwell radiator needs different ones. The config already supports it.

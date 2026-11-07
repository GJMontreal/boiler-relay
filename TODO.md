# TODO

Build order is fixed: hardening and config (done), deploy and shadow, API and UI.

## Step 2: deploy, switch and shadow

- [x] Add `--shadow` to `python -m boiler_relay`. Read the same sensor keys, compute the same decisions, touch no GPIO, send no MQTT, and write only under `boiler_relay/shadow/`.
- [x] Publish zone, boiler and heartbeat state under `boiler_relay/<mode>/` from the active service as well. Keep writing the Homebridge keys from the active service.
- [x] Rename the new service `boiler_relay_v2`, installed in `/var/lib/boiler_relay_v2`, running as `heating` through a `<service_user>` placeholder.
- [x] Add `boiler_relay_v2_shadow.service`. It conflicts with v2, not with legacy, and is never enabled at boot.
- [x] Add `Conflicts=` to the v2 unit and a drop-in file for the legacy unit.
- [x] Keep `switch.sh` away from `mqtt_bridge.service`. The legacy, v2 and shadow services and Homebridge all read what the bridge writes. Note in the deploy docs that the bridge lives in `GJMontreal/mqtt-bridge`.
- [x] Add `deploy/switch.sh legacy|v2|shadow`. It stops the old service, waits, starts the new one and moves the boot-time enable. It runs over `ssh -t` with sudo.
- [x] Rewrite `deploy.sh` to use `rsync --delete` with `.venv` excluded, to derive paths from the service name, and to refuse the legacy directory.
- [x] Move `After=redis.service` from `[Service]` to `[Unit]` in the unit template.
- [ ] Compare legacy and shadow per zone and per ten-minute window: mean control value and on-fraction.
- [ ] First deploy at the house during heating season. Watch each zone open and close once and check the boiler follows the end switches. Roll back with `switch.sh legacy`.
- [ ] Install `paho-mqtt` 2.x, `simple-pid` and `redis==3.5.3` on the device's Python 3.7 in the new venv.

## Step 3: API and UI

- [ ] `api/`: a read-only FastAPI service on the LAN with no authentication. Pin FastAPI and pydantic versions that support Python 3.7 and check them when the venv is first built. Pinned in `api/requirements.txt`, and `/api/live` and `/api/services` exist. Logs, history and the unit are still open.
- [ ] Run it as a new user, `boiler_relay_api`, in the `systemd-journal` group, with its own unit.
- [ ] Sample redis every 10 seconds into SQLite on the USB drive, keep seven days, and include the legacy keys. Mount the drive by UUID as ext4 with `nofail`. Without the drive, run without history and never write to the eMMC.
- [ ] Show `mqtt_bridge.service` state and each sensor's age on the Live page. If the bridge dies, every zone calls for no heat after two hours.
- [ ] Include `mqtt_bridge.service` in the Logs page alongside the control services.
- [ ] `web/`: plain HTML and JavaScript with a small chart library, served by FastAPI. Pages: Live, Trends, Logs (from the journal) and Compare.

## Backlog

- [ ] Boiler short-cycling protection (a minimum on and off time). Deferred until the problem shows.
- [ ] Publish a real MQTT message from `MQTTRelay` with the real topic and device and check the Zigbee relay switches. Publishing to a broker already passes.
- [ ] Revisit sending relay commands through redis and the bridge, which would drop paho from the control process. Not now, because the radiator would then depend on the bridge to switch.
- [ ] Homebridge needs a stairwell thermostat that writes `/home/sensors/stairwell/target_temperature` and `target_heatingcooling_state`. Until it does, the Stairwell zone idles.
- [ ] Confirm the Bedrooms end-switch pairing: `P8_10` with `P8_9` and `P8_14` with `P8_17`.
- [ ] The device's login banner prints the default `debian` password. Change it and consider key-only ssh.
- [ ] The `back_room` sensor stopped reporting on 2026-10-24. Check its battery.
- [ ] Add a GPIO pull-up or pull-down choice for the end-switch inputs if the wiring needs one.
- [ ] Move PID gains per zone only if the stairwell radiator needs different ones. The config already supports it.

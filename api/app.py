import subprocess
from datetime import datetime, timezone
from json import loads
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from boiler_relay.state_publisher import ACTIVE, SHADOW, TIME_FORMAT
from boiler_relay.zone import STALE_AFTER

SERVICES = ("boiler_relay", "boiler_relay_v2", "boiler_relay_v2_shadow", "mqtt_bridge")
SYSTEMCTL_TIMEOUT = 5


class Reading(BaseModel):
    value: float
    time: str
    age_seconds: Optional[float]


class ZoneLive(BaseModel):
    name: str
    sensor_path: str
    current_temperature: Optional[Reading]
    sensor_stale: bool
    target_temperature: Optional[float]
    target_state: Optional[int]
    control_value: Optional[float]
    heating_cooling_state: Optional[int]
    boost: Optional[bool]
    active: Optional[dict]
    shadow: Optional[dict]


class ServiceState(BaseModel):
    name: str
    state: str


def unit_state(name):
    try:
        result = subprocess.run(["systemctl", "is-active", f"{name}.service"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                universal_newlines=True, timeout=SYSTEMCTL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() or "unknown"


def age_of(sample_time):
    try:
        reported = datetime.strptime(sample_time, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - reported).total_seconds())


def create_app(system, redis, unit_state=unit_state):
    app = FastAPI(title="boiler_relay")

    def read_json(key):
        message = redis.get(key)
        return None if message is None else loads(message)

    def read_int(key):
        message = redis.get(key)
        try:
            return None if message is None else int(message)
        except ValueError:
            return None

    def read_reading(path):
        data = read_json(f"{path}/current_temperature")
        if data is None:
            return None
        return Reading(value=data["value"], time=data["time"], age_seconds=age_of(data["time"]))

    def read_zone(zone):
        path = zone.sensor_path
        reading = read_reading(path)
        target = read_json(f"{path}/target_temperature")
        control = redis.get(zone.control_path)
        return ZoneLive(
            name=zone.name,
            sensor_path=path,
            current_temperature=reading,
            sensor_stale=reading is None or reading.age_seconds is None or reading.age_seconds > STALE_AFTER,
            target_temperature=None if target is None else target["value"],
            target_state=read_int(f"{path}/target_heatingcooling_state"),
            control_value=None if control is None else float(control),
            heating_cooling_state=read_int(f"{path}/heating_cooling_state"),
            boost=read_json(f"{path}/boost"),
            active=read_json(f"heating/{ACTIVE}/zones/{zone.name}"),
            shadow=read_json(f"heating/{SHADOW}/zones/{zone.name}"),
        )

    @app.get("/api/live", response_model=List[ZoneLive])
    def live():
        return [read_zone(zone) for zone in system.zones]

    @app.get("/api/services", response_model=List[ServiceState])
    def services():
        return [ServiceState(name=name, state=unit_state(name)) for name in SERVICES]

    return app

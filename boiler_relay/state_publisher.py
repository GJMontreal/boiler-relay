from datetime import datetime, timezone
from json import dumps

ACTIVE = "active"
SHADOW = "shadow"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class StatePublisher:
    def __init__(self, redis, mode):
        self.redis = redis
        self.prefix = f"boiler_relay/{mode}"

    def zone(self, name, control_value, state):
        self.write(f"zones/{name}", {"control_value": control_value, "state": state})

    def boiler(self, call):
        self.write("boiler", {"call": call})

    def heartbeat(self):
        self.write("heartbeat", {})

    def write(self, suffix, payload):
        payload["time"] = datetime.now(timezone.utc).strftime(TIME_FORMAT)
        self.redis.set(f"{self.prefix}/{suffix}", dumps(payload))

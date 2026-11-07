from datetime import datetime, timezone
from json import dumps

from boiler_relay.version import __version__, read_commit

ACTIVE = "active"
SHADOW = "shadow"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
VERSION_KEY = "heating/versions/boiler-relay"


def now():
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def publish_version(redis):
    payload = {"version": __version__, "commit": read_commit(), "time": now()}
    redis.set(VERSION_KEY, dumps(payload))


class StatePublisher:
    def __init__(self, redis, mode):
        self.redis = redis
        self.prefix = f"heating/{mode}"

    def zone(self, name, system, control_value, state):
        self.write(f"zones/{name}", {"system": system, "control_value": control_value, "state": state})

    def boiler(self, call):
        self.write("hydronic/boiler", {"call": call})

    def heartbeat(self):
        self.write("heartbeat", {})

    def write(self, suffix, payload):
        payload["time"] = now()
        self.redis.set(f"{self.prefix}/{suffix}", dumps(payload))

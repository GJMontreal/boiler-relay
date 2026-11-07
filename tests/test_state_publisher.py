import json

from boiler_relay.state_publisher import ACTIVE, SHADOW, StatePublisher


def read(redis_client, key):
  return json.loads(redis_client.get(key))


def test_zone_state_is_written_under_the_mode_prefix(redis_client):
  StatePublisher(redis_client, SHADOW).zone("Bedrooms", "hydronic", 0.25, 1)

  data = read(redis_client, "heating/shadow/zones/Bedrooms")
  assert data["system"] == "hydronic"
  assert data["control_value"] == 0.25
  assert data["state"] == 1
  assert data["time"].endswith("Z")


def test_boiler_and_heartbeat_are_written_under_the_mode_prefix(redis_client):
  publisher = StatePublisher(redis_client, ACTIVE)

  publisher.boiler(1)
  publisher.heartbeat()

  assert read(redis_client, "heating/active/hydronic/boiler")["call"] == 1
  assert read(redis_client, "heating/active/heartbeat")["time"].endswith("Z")


def test_nothing_is_written_outside_the_prefix(redis_client):
  publisher = StatePublisher(redis_client, SHADOW)

  publisher.zone("Bedrooms", "hydronic", 0.0, None)
  publisher.boiler(0)
  publisher.heartbeat()

  assert all(key.startswith(b"heating/shadow/") for key in redis_client.keys())

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


def test_zone_state_carries_the_pid_profile_when_given(redis_client):
  profile = {"kp": 1, "ki": 0.001, "kd": 0, "integral_cap": 0.3}

  StatePublisher(redis_client, SHADOW).zone("Bedrooms", "hydronic", 0.25, 1, profile)

  assert read(redis_client, "heating/shadow/zones/Bedrooms")["pid"] == profile


def test_zone_state_has_no_pid_when_none_is_given(redis_client):
  StatePublisher(redis_client, SHADOW).zone("Bedrooms", "hydronic", 0.25, 1)

  assert "pid" not in read(redis_client, "heating/shadow/zones/Bedrooms")


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

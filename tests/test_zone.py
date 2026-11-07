from src.config import RedisConfig, ZoneConfig
from src.zone import Zone


def test_zone_reads_sensor_and_writes_control_value(redis_client):
  config = ZoneConfig(
    sensor_path="/home/sensors/a",
    name="Bedrooms",
    outputs=[],
    pid_interval="10",
    control_interval="10",
  )

  zone = Zone(config, RedisConfig(host="localhost", port=6379))

  assert zone.name == "Bedrooms"
  assert zone.input_path == "/home/sensors/a"
  assert zone.output_path == "/home/sensors/a/control_value"
  assert zone.pid_thread.pid_interval == 10.0

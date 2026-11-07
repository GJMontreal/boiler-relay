import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CONFIG = {
  "redis": {"host": "localhost", "port": 6379},
  "boiler": {"output_gpio": "P8_18"},
  "zones": [{
    "sensor_path": "/home/sensors/a",
    "name": "Bedrooms",
    "system": "hydronic",
    "outputs": [{"type": "gpio", "pin": "P8_10", "end_switch": "P8_9"}],
    "pid_interval": 10,
  }],
}

SCRIPT = """
import sys, time
import fakeredis
from boiler_relay import __main__ as entry, boiler_thread, zone

server = fakeredis.FakeServer()
connect = lambda **kwargs: fakeredis.FakeRedis(server=server)
zone.Redis = connect
entry.Redis = connect
zone.sleep = boiler_thread.sleep = lambda seconds: time.sleep(0.05)
entry.supervise = lambda threads, stop: (time.sleep(1.0), 0)[1]

client = fakeredis.FakeRedis(server=server)
client.set("/home/sensors/a/current_temperature", '{"value": 15, "time": "2099-01-01T00:00:00Z"}')
client.set("/home/sensors/a/target_temperature", '{"value": 21}')
client.set("/home/sensors/a/target_heatingcooling_state", 1)

code = entry.main(sys.argv[1:])
print(sorted(key.decode() for key in client.keys() if key.startswith(b"heating/")))
sys.exit(code)
"""


@pytest.fixture
def run(tmp_path):
  fake = tmp_path / "fake_bbio"
  (fake / "Adafruit_BBIO").mkdir(parents=True)
  (fake / "Adafruit_BBIO" / "__init__.py").write_text('raise AssertionError("Adafruit_BBIO was imported")\n')
  (fake / "Adafruit_BBIO" / "GPIO.py").write_text('raise AssertionError("Adafruit_BBIO.GPIO was imported")\n')
  config = tmp_path / "config.json"
  config.write_text(json.dumps(CONFIG))

  def go(*flags):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(fake), str(ROOT)])}
    return subprocess.run([sys.executable, "-c", SCRIPT, "-c", str(config), *flags],
                          env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=60)

  return go


def test_a_full_shadow_run_never_touches_the_real_gpio(run):
  result = run("--shadow")

  assert result.returncode == 0, result.stderr
  assert "Adafruit_BBIO" not in result.stderr
  assert "heating/shadow/zones/Bedrooms" in result.stdout
  assert "heating/shadow/hydronic/boiler" in result.stdout


def test_the_fake_gpio_does_fail_an_active_run(run):
  result = run()

  assert result.returncode != 0
  assert "Adafruit_BBIO was imported" in result.stderr

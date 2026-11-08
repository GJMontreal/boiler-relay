import subprocess
from configparser import ConfigParser
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"

SSH = (
  'echo "$*" >> "$LOG"\n'
  '[ "$1" = -t ] && shift\n'
  'shift\n'
  '[ "$1" = sudo ] && shift\n'
  'case "$2" in\n'
  '  cat) grep -qx "${3%.service}" "$STATE/installed" ;;\n'
  '  is-active) grep -qx "${4%.service}" "$STATE/active" ;;\n'
  '  start) echo "${3%.service}" >> "$STATE/active"; echo "start ${3%.service}" >> "$STATE/changes" ;;\n'
  '  stop) grep -vx "${3%.service}" "$STATE/active" > "$STATE/rest"; mv "$STATE/rest" "$STATE/active"; echo "stop ${3%.service}" >> "$STATE/changes" ;;\n'
  '  enable|disable) echo "$2 ${3%.service}" >> "$STATE/changes" ;;\n'
  'esac\n'
  'exit $?\n'
)


def read_unit(name):
  parser = ConfigParser(strict=False, interpolation=None)
  parser.optionxform = str
  parser.read(str(DEPLOY / name))
  return parser


@pytest.fixture
def switch(tmp_path):
  bin_dir = tmp_path / "bin"
  bin_dir.mkdir()
  for name, body in {"ssh": SSH, "sleep": "exit 0\n"}.items():
    stub = bin_dir / name
    stub.write_text("#!/bin/sh\n" + body)
    stub.chmod(0o755)
  state = tmp_path / "state"
  state.mkdir()
  (state / "installed").write_text("boiler_relay\nboiler_relay_v2\nboiler_relay_v2_shadow\n")
  (state / "active").write_text("boiler_relay\n")

  def go(*args):
    result = subprocess.run(
      ["/bin/bash", str(DEPLOY / "switch.sh"), "debian", "device", *args],
      env={"PATH": "{}:/usr/bin:/bin".format(bin_dir), "LOG": str(tmp_path / "log"), "STATE": str(state)},
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
    changes = state / "changes"
    return result, changes.read_text().splitlines() if changes.exists() else []

  return go


def test_the_shadow_unit_starts_at_boot():
  assert read_unit("boiler_relay_v2_shadow.service.template")["Install"]["WantedBy"] == "multi-user.target"


def test_the_shadow_unit_cannot_enable_or_pull_in_v2():
  unit = read_unit("boiler_relay_v2_shadow.service.template")

  assert not unit.has_option("Install", "Also")
  assert not unit.has_option("Install", "RequiredBy")
  for key in ("Wants", "Requires", "Requisite", "BindsTo", "PartOf", "Upholds"):
    assert not unit.has_option("Unit", key)


@pytest.mark.parametrize("name", ["boiler_relay_v2.service.template", "boiler_relay_v2_shadow.service.template"])
def test_both_units_start_after_redis_and_the_broker(name):
  after = read_unit(name)["Unit"]["After"].split()

  assert "redis-server.service" in after
  assert "mosquitto.service" in after


@pytest.mark.parametrize("name", ["boiler_relay_v2.service.template", "boiler_relay_v2_shadow.service.template"])
def test_both_units_retry_slowly_and_never_give_up(name):
  unit = read_unit(name)

  assert unit["Service"]["Restart"] == "on-failure"
  assert unit["Service"]["RestartSec"] == "5"
  assert unit["Unit"]["StartLimitIntervalSec"] == "0"
  assert not unit.has_option("Service", "StartLimitIntervalSec")


def test_v2_conflicts_with_legacy_only_and_the_shadow_conflicts_with_nothing():
  v2 = read_unit("boiler_relay_v2.service.template")["Unit"]["Conflicts"].split()

  assert v2 == ["boiler_relay.service"]
  assert not read_unit("boiler_relay_v2_shadow.service.template").has_option("Unit", "Conflicts")


def test_the_legacy_unit_is_never_enabled_by_a_shadow_unit():
  assert not (DEPLOY / "boiler_relay_v2_shadow.service.template").read_text().count("boiler_relay.service")


def test_switching_to_shadow_enables_the_shadow_and_never_v2(switch):
  result, changes = switch("shadow")

  assert result.returncode == 0, result.stderr
  assert changes == [
    "stop boiler_relay_v2",
    "start boiler_relay",
    "start boiler_relay_v2_shadow",
    "enable boiler_relay",
    "enable boiler_relay_v2_shadow",
    "disable boiler_relay_v2",
  ]


def test_switching_to_v2_stops_and_disables_only_legacy(switch):
  result, changes = switch("v2", "--confirm")

  assert result.returncode == 0, result.stderr
  assert changes == [
    "stop boiler_relay",
    "start boiler_relay_v2",
    "enable boiler_relay_v2",
    "disable boiler_relay",
  ]


def test_switching_to_v2_leaves_a_running_shadow_alone(switch, tmp_path):
  (tmp_path / "state" / "active").write_text("boiler_relay\nboiler_relay_v2_shadow\n")

  result, changes = switch("v2", "--confirm")

  assert result.returncode == 0, result.stderr
  assert not any("boiler_relay_v2_shadow" in change for change in changes)
  assert (tmp_path / "state" / "active").read_text().split() == ["boiler_relay_v2_shadow", "boiler_relay_v2"]


def test_switching_to_legacy_disables_the_shadow(switch):
  result, changes = switch("legacy")

  assert result.returncode == 0, result.stderr
  assert changes == [
    "stop boiler_relay_v2",
    "stop boiler_relay_v2_shadow",
    "start boiler_relay",
    "enable boiler_relay",
    "disable boiler_relay_v2",
    "disable boiler_relay_v2_shadow",
  ]


def test_switching_to_v2_without_confirm_changes_nothing(switch):
  result, changes = switch("v2")

  assert result.returncode == 1
  assert changes == []


def test_switching_to_v2_lists_only_legacy_as_stopped(switch, tmp_path):
  (tmp_path / "state" / "active").write_text("boiler_relay\nboiler_relay_v2_shadow\n")

  result, _ = switch("v2")

  assert "switching to v2 will stop: boiler_relay\n" in result.stdout

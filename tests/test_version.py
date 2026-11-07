import json
import re

import pytest

from boiler_relay import version
from boiler_relay.state_publisher import VERSION_KEY, publish_version


def test_the_version_is_semantic():
  assert re.fullmatch(r"\d+\.\d+\.\d+", version.__version__)


def test_the_commit_is_read_from_the_build_file(tmp_path):
  path = tmp_path / "build_info.json"
  path.write_text(json.dumps({"version": "0.1.0", "commit": "abc1234-dirty"}))

  assert version.read_commit(path) == "abc1234-dirty"


def test_a_missing_build_file_gives_an_unknown_commit(tmp_path):
  assert version.read_commit(tmp_path / "missing.json") == "unknown"


@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"commit": null}'])
def test_an_unreadable_build_file_gives_an_unknown_commit(tmp_path, content):
  path = tmp_path / "build_info.json"
  path.write_text(content)

  assert version.read_commit(path) == "unknown"


def test_describe_names_the_package_version_and_commit(tmp_path):
  path = tmp_path / "build_info.json"
  path.write_text(json.dumps({"commit": "abc1234"}))

  assert version.describe(path) == f"boiler_relay {version.__version__} (abc1234)"


def test_the_version_flag_prints_and_exits_zero(capsys):
  from boiler_relay import __main__ as entry

  with pytest.raises(SystemExit) as exit_info:
    entry.parse_arguments(["--version"])

  assert exit_info.value.code == 0
  assert capsys.readouterr().out.startswith(f"boiler_relay {version.__version__} (")


def test_publish_version_sets_the_key_without_publishing(redis_client, monkeypatch):
  monkeypatch.setattr("boiler_relay.state_publisher.read_commit", lambda: "abc1234")
  channel = redis_client.pubsub()
  channel.subscribe(VERSION_KEY)
  channel.get_message()

  publish_version(redis_client)

  data = json.loads(redis_client.get(VERSION_KEY))
  assert VERSION_KEY == "heating/versions/boiler-relay"
  assert data["version"] == version.__version__
  assert data["commit"] == "abc1234"
  assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["time"])
  assert set(data) == {"version", "commit", "time"}
  assert channel.get_message() is None

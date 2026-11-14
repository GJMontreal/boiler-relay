import csv
import io
import sqlite3

from tools import export_samples, replay_limiter

HEADER = ["zone", "ts", "sh_ctl", "ctl", "mode", "boost", "out", "target"]


def samples(zone, control, rows, mode="1", boost="0"):
  return [{"zone": zone, "ts": str(1000 + index * 10), "sh_ctl": str(control), "ctl": str(control),
           "mode": mode, "boost": boost, "out": "", "target": "21"} for index in range(rows)]


def test_the_replay_removes_short_calls_and_keeps_the_mean_heat():
  result = replay_limiter.replay(samples("Study", 0.1, 3000), "ctl", 5, 13)["Study"]

  assert result.baseline.short > 0
  assert result.limited.short <= 1
  assert result.limited.reopens == 0
  assert abs(result.limited.on_fraction - result.baseline.on_fraction) < 0.01


def test_the_replay_with_no_minimums_matches_the_baseline():
  result = replay_limiter.replay(samples("Study", 0.5, 600), "ctl", 0.01, 0.01)["Study"]

  assert result.limited.on_fraction == result.baseline.on_fraction


def test_the_replay_keeps_each_zone_apart():
  rows = samples("Study", 0.1, 600) + samples("Kitchen", 0.5, 600)

  assert sorted(replay_limiter.replay(rows, "ctl", 5, 13)) == ["Kitchen", "Study"]


def test_the_replay_ignores_rows_without_the_column():
  rows = samples("Study", 0.5, 100)
  for row in rows:
    row["sh_ctl"] = ""

  assert replay_limiter.replay(rows, "sh_ctl", 5, 13) == {}


def test_the_replay_ignores_boost_ticks():
  result = replay_limiter.replay(samples("Study", 1.0, 100, boost="1"), "ctl", 5, 13)["Study"]

  assert result.ticks == 0
  assert result.baseline.calls == 0


def test_the_export_writes_the_four_hydronic_zones(tmp_path):
  path = tmp_path / "history.sqlite3"
  connection = sqlite3.connect(path)
  connection.execute("create table zones (id integer primary key, name text)")
  connection.execute("create table samples (zone integer, ts integer, sh_ctl real, ctl real, mode integer, boost integer, out integer, target real)")
  connection.executemany("insert into zones values (?, ?)", [(1, "Study"), (2, "Stairwell")])
  connection.executemany("insert into samples values (?, 1000, 0.5, 0.4, 1, 0, 1, 21)", [(1,), (2,)])
  connection.commit()
  connection.close()
  output = io.StringIO()

  export_samples.export(str(path), output)

  rows = list(csv.reader(io.StringIO(output.getvalue())))
  assert rows[0] == HEADER
  assert [row[0] for row in rows[1:]] == ["Study"]

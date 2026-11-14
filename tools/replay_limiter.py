import argparse
import csv
import logging
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boiler_relay.config import ValveLimitsConfig
from boiler_relay.valve_limiter import ValveLimiter

DURATION = 120
TICK = 5
GAP = 60
SHORT_CALL = 5
SHORT_GAP = 13

Summary = namedtuple("Summary", "calls short reopens on_fraction median")
Result = namedtuple("Result", "ticks mean_control baseline limited")


def runs(flags):
    found = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        if not flag and start is not None:
            found.append((start, index))
            start = None
    if start is not None:
        found.append((start, len(flags)))
    return found


def summarize(flags, heat_ticks):
    found = runs(flags)
    lengths = [(end - start) * TICK / 60 for start, end in found]
    gaps = [(found[index + 1][0] - found[index][1]) * TICK / 60 for index in range(len(found) - 1)]
    return Summary(
        calls=len(found),
        short=sum(length < SHORT_CALL for length in lengths),
        reopens=sum(gap < SHORT_GAP for gap in gaps),
        on_fraction=sum(flags) / heat_ticks if heat_ticks else 0.0,
        median=sorted(lengths)[len(lengths) // 2] if lengths else 0.0,
    )


def replay_zone(name, rows, column, min_on, min_off):
    baseline, limited = [], []
    control_sum = 0.0
    heat_ticks = 0
    limiter = ValveLimiter(name, min_on * 60, min_off * 60)
    cycle = 0
    previous = None
    for row in rows:
        stamp = int(row["ts"])
        if previous is not None and stamp - previous > GAP:
            limiter = ValveLimiter(name, min_on * 60, min_off * 60)
            cycle = 0
            baseline.append(False)
            limited.append(False)
        previous = stamp
        if row["mode"] == "":
            limiter.cut(TICK * 2)
            continue
        heat = row["mode"] == "1"
        boost = row["boost"] == "1"
        control = float(row[column])
        for _ in range(2):
            on_ticks = int(control * DURATION)
            demand = heat and on_ticks > cycle
            calling = heat and control > 0
            pending = max(0, on_ticks - cycle - 1) * TICK if calling else 0
            opened = limiter.step(demand, calling, TICK, pending, boost=boost, cut=not heat)
            if not boost:
                baseline.append(demand)
                limited.append(opened)
                if heat:
                    heat_ticks += 1
                    control_sum += control
            cycle += 1
            if cycle > DURATION - 1:
                cycle = 0
    mean_control = control_sum / heat_ticks if heat_ticks else 0.0
    return Result(heat_ticks, mean_control, summarize(baseline, heat_ticks), summarize(limited, heat_ticks))


def replay(rows, column, min_on, min_off):
    zones = {}
    for row in rows:
        if row[column] != "":
            zones.setdefault(row["zone"], []).append(row)
    return {name: replay_zone(name, zone_rows, column, min_on, min_off) for name, zone_rows in zones.items()}


def describe(label, summary):
    return ("  %-9s calls %3d  under %d min %3d  reopen after under %d min off %3d  on fraction %.3f  median call %.1f min"
            % (label, summary.calls, SHORT_CALL, summary.short, SHORT_GAP, summary.reopens,
               summary.on_fraction, summary.median))


def main():
    defaults = ValveLimitsConfig()
    parser = argparse.ArgumentParser(description="Replay the valve limiter over exported zone samples")
    parser.add_argument("samples", help="CSV written by tools/export_samples.py")
    parser.add_argument("column", choices=["ctl", "sh_ctl"], help="control value column to replay")
    parser.add_argument("--min-on", type=float, default=defaults.min_on_time, help="minimum on time in minutes")
    parser.add_argument("--min-off", type=float, default=defaults.min_off_time, help="minimum off time in minutes")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    with open(args.samples) as file:
        rows = list(csv.DictReader(file))
    for name, result in sorted(replay(rows, args.column, args.min_on, args.min_off).items()):
        print("==", name, "heat-mode ticks", result.ticks, "mean control %.3f" % result.mean_control)
        print(describe("baseline", result.baseline))
        print(describe("limited", result.limited))


if __name__ == "__main__":
    main()

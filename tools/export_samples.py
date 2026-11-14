import csv
import sqlite3
import sys

DATABASE = "/var/lib/heating_history/data/history.sqlite3"
ZONES = ("Bedrooms", "Common", "Kitchen", "Study")
QUERY = ("select z.name, s.ts, s.sh_ctl, s.ctl, s.mode, s.boost, s.out, s.target "
         "from samples s join zones z on z.id = s.zone "
         "where z.name in (%s) order by z.name, s.ts" % ",".join("?" * len(ZONES)))


def export(database, output):
    connection = sqlite3.connect("file:%s?mode=ro" % database, uri=True)
    writer = csv.writer(output)
    writer.writerow(["zone", "ts", "sh_ctl", "ctl", "mode", "boost", "out", "target"])
    for row in connection.execute(QUERY, ZONES):
        writer.writerow(row)


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else DATABASE, sys.stdout)

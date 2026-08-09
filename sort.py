#!/usr/bin/env python3
"""Sort the Summer Movie Wager CSVs.

The order here has to match the sortedness assertions in the data branch's
validate.sql, which is why this stays as code rather than an instruction.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

SORT_KEYS = {
    "years.csv": lambda row: (int(row["year"]),),
    "movies.csv": lambda row: (int(row["year"]), row["title"]),
    "lists.csv": lambda row: (
        int(row["year"]),
        row["player_name"],
        int(row["position"]),
    ),
}


def sort_csv(path: Path) -> int:
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    rows.sort(key=SORT_KEYS[path.name])

    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    data_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    for name in SORT_KEYS:
        print(f"{name}: {sort_csv(data_path / name)} rows")

import csv
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class ErrorContext:
    filename: str
    lineno: int
    field_name: str | None


context: ErrorContext = ErrorContext("", 0, None)
error_count: int = 0
warning_count: int = 0

CURRENT_YEAR: int = date.today().year


def main() -> None:
    data_path = Path(sys.argv[1])
    _assert(data_path.exists(), "data path does not exist")

    context.filename = "lists.csv"
    lists_path = data_path / "lists.csv"
    _assert(lists_path.exists(), "file does not exist")

    context.filename = "movies.csv"
    movies_path = data_path / "movies.csv"
    _assert(movies_path.exists(), "file does not exist")

    context.filename = "years.csv"
    years_path = data_path / "years.csv"
    _assert(years_path.exists(), "file does not exist")

    list_rows = list(csv.DictReader(lists_path.open("r")))
    movie_rows = list(csv.DictReader(movies_path.open("r")))
    year_rows = list(csv.DictReader(years_path.open("r")))

    context.filename = "years.csv"
    for row in _enumerate_rows("years.csv", year_rows):
        context.field_name = "year"
        _assert(row["year"].isdigit(), "Invalid year")
        # _warn(int(row["year"]) >= 2007, "Year too old")

        if row["start_date"]:
            context.field_name = "start_date"
            _assert(_is_date_isoformat(row["start_date"]), "Invalid date format")
        if row["end_date"]:
            context.field_name = "end_date"
            _assert(_is_date_isoformat(row["end_date"]), "Invalid date format")
        if row["start_date"] and row["end_date"]:
            context.field_name = "start_date"
            _warn(
                date.fromisoformat(row["start_date"])
                < date.fromisoformat(row["end_date"]),
                "Start date is after end date",
            )

        if row["year"] != str(CURRENT_YEAR):
            context.field_name = "host_winner_name"
            _warn(row["host_winner_name"] != "", "Missing host winner name")

        context.field_name = None

    _warn(
        _is_sorted(key=lambda row: int(row["year"]), rows=year_rows),
        "not sorted",
    )

    context.filename = "movies.csv"
    for row in _enumerate_rows("movies.csv", movie_rows):
        context.field_name = "year"
        _assert(row["year"].isdigit(), "Invalid year")
        # _warn(int(row["year"]) >= 2007, "Year too old")

        if row["imdb_id"]:
            context.field_name = "imdb_id"
            _assert(row["imdb_id"].startswith("tt"), "Invalid IMDb ID")

        if row["boxofficemojo_id"]:
            context.field_name = "boxofficemojo_id"
            _assert(
                row["boxofficemojo_id"].startswith("rl"), "Invalid Box Office Mojo ID"
            )

        if row["tmdb_id"]:
            context.field_name = "tmdb_id"
            _assert(row["tmdb_id"].isdigit(), "Invalid TMDB ID")

        if row["qid"]:
            context.field_name = "qid"
            _assert(row["qid"].startswith("Q"), "Invalid Wikidata ID")

    _warn(
        _is_sorted(key=lambda row: (int(row["year"]), row["title"]), rows=movie_rows),
        "not sorted",
    )

    context.filename = "lists.csv"
    _warn(
        _is_sorted(
            key=lambda row: (
                int(row["year"]),
                row["player_name"],
                int(row["position"]),
            ),
            rows=list_rows,
        ),
        "not sorted",
    )

    if error_count > 0:
        print(f"{error_count} errors", file=sys.stderr)
    if warning_count > 0:
        print(f"{warning_count} warnings", file=sys.stderr)
    exit(1 if error_count > 0 else 0)


def _assert(expression: bool, message: str) -> bool:
    global error_count
    global context
    if not expression:
        error_count += 1
        params: list[str] = []
        if context.filename:
            params.append(f"file={context.filename}")
        if context.lineno:
            params.append(f"line={context.lineno}")
        if context.field_name:
            params.append(f"title={context.field_name}")
        params_str = ",".join(params)
        print(f"::error {params_str}::{message}", file=sys.stderr)
    return expression


def _warn(expression: bool, message: str) -> bool:
    global warning_count
    global context
    if not expression:
        warning_count += 1
        params: list[str] = []
        if context.filename:
            params.append(f"file={context.filename}")
        if context.lineno:
            params.append(f"line={context.lineno}")
        if context.field_name:
            params.append(f"title={context.field_name}")
        params_str = ",".join(params)
        print(f"::warning {params_str}::{message}", file=sys.stderr)
    return expression


def _enumerate_rows(
    filename: str, rows: Iterable[dict[str, str]]
) -> Iterator[dict[str, str]]:
    context.filename = filename
    for idx, row in enumerate(rows):
        context.lineno = idx + 2
        context.field_name = None
        yield row
    context.lineno = 0
    context.field_name = None


def _is_sorted(key: Callable[[Any], Any], rows: list[Any]) -> bool:
    return all(key(rows[i]) <= key(rows[i + 1]) for i in range(len(rows) - 1))


def _is_date_isoformat(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()

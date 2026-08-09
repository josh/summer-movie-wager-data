import csv
import gzip
import io
import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from random import shuffle
from time import sleep
from typing import Any

import click
import requests

from thesummermoviewager import playalong

logger = logging.getLogger(__name__)

CURRENT_YEAR: int = datetime.now(timezone.utc).year

TIMEOUT = 30
USER_AGENT = "summer-movie-wager-data (https://github.com/josh/summer-movie-wager-data)"


@click.group()
@click.option("--verbose", "-v", is_flag=True)
def cli(verbose: bool) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level)


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
def sort(data_path: Path) -> None:
    with load_csv_data(data_path / "years.csv") as rows:
        rows.sort(key=lambda row: int(row["year"]))

    with load_csv_data(data_path / "movies.csv") as rows:
        rows.sort(key=lambda row: (int(row["year"]), row["title"]))

    with load_csv_data(data_path / "lists.csv") as rows:
        rows.sort(
            key=lambda row: (int(row["year"]), row["player_name"], int(row["position"]))
        )


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
@click.option("--limit", type=int, default=25)
def backfill_wikidata_info(data_path: Path, limit: int) -> None:
    with load_csv_data(data_path / "movies.csv") as rows:
        rows_missing_info = [
            row
            for row in rows
            if row["imdb_id"] != "" and (row["qid"] == "" or row["tmdb_id"] == "")
        ]
        shuffle(rows_missing_info)
        for row in islice(rows_missing_info, limit):
            qid, tmdb_id = _sparql_find_film_by_imdb(row["imdb_id"])
            if qid and tmdb_id:
                row["qid"] = qid
                row["tmdb_id"] = tmdb_id


_SPARQL_FIND_BY_IMDB_ID = """
SELECT ?item ?tmdb_id WHERE { ?item wdt:P345 "?imdb_id"; wdt:P4947 ?tmdb_id. }
"""


def _wikidata_sparql(query: str) -> list[dict[str, Any]]:
    """Run a SPARQL query against Wikidata.

    The User-Agent is not optional. query.wikidata.org returns 403 to the
    default requests UA, which is why the backfill commands silently stopped
    working and 2025 has no qid or tmdb_id.
    """
    sleep(1)
    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    bindings: list[dict[str, Any]] = response.json()["results"]["bindings"]
    return bindings


def _sparql_find_film_by_imdb(imdb_id: str) -> tuple[str, str] | tuple[None, None]:
    query = _SPARQL_FIND_BY_IMDB_ID.replace("?imdb_id", imdb_id)

    if results := _wikidata_sparql(query):
        qid = results[0]["item"]["value"].replace("http://www.wikidata.org/entity/", "")
        tmdb_id = results[0]["tmdb_id"]["value"]
        return qid, tmdb_id
    else:
        logger.warning(f"Failed to find Wikidata info for {imdb_id}")
        return None, None


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
def discover_playalong_movies(data_path: Path) -> None:
    year = str(CURRENT_YEAR)

    with load_csv_data(data_path / "movies.csv") as rows:
        known_movie_titles = {(row["year"], row["title"]) for row in rows}
        known_imdb_ids = {
            (row["year"], row["imdb_id"]) for row in rows if row["imdb_id"]
        }

        for movie in playalong():
            if (year, movie.title) in known_movie_titles:
                continue

            # The feed occasionally maps two titles to one IMDb id. In 2026 it
            # gave "Fall 2" the id for "Animal Farm". Adding it anyway would
            # silently duplicate an id, so flag it and let a human resolve it.
            if movie.imdb_id and (year, movie.imdb_id) in known_imdb_ids:
                logger.warning(
                    f"Skipping '{movie.title}' ({year}): "
                    f"{movie.imdb_id} is already used by another {year} film"
                )
                continue

            logger.info(f"Adding '{movie.title}' ({year})")
            rows.append(
                {
                    "year": year,
                    "title": movie.title,
                    "imdb_id": movie.imdb_id,
                    "boxofficemojo_id": movie.mojo_id,
                }
            )
            known_movie_titles.add((year, movie.title))
            if movie.imdb_id:
                known_imdb_ids.add((year, movie.imdb_id))


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
def fetch_imdb_titles(data_path: Path) -> None:
    response = requests.get(
        "https://datasets.imdbws.com/title.basics.tsv.gz",
        stream=True,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    decompressed = gzip.GzipFile(fileobj=response.raw)
    textio = io.TextIOWrapper(decompressed, encoding="utf-8")
    csv_reader = csv.DictReader(textio, delimiter="\t")

    imdb_titles: dict[str, str] = {}
    for row in csv_reader:
        imdb_titles[row["tconst"]] = row["primaryTitle"]
    assert len(imdb_titles) > 0, "No IMDb titles found"

    with load_csv_data(data_path / "movies.csv") as rows:
        for row in rows:
            if row["imdb_id"] in imdb_titles:
                row["title"] = imdb_titles[row["imdb_id"]]


@contextmanager
def load_csv_data(path: Path) -> Generator[list[dict[str, str]], None, None]:
    filename = str(path)

    fieldnames: list[str] = []
    rows: list[dict[str, str]] = []

    with click.open_file(filename=filename, mode="r") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames
        fieldnames = list(reader.fieldnames)
        assert len(fieldnames) > 0
        rows.extend(reader)
        logger.debug(f"Loaded {len(rows)} rows from {filename}")

    yield rows

    with click.open_file(filename=filename, mode="w") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        logger.debug(f"Saved {len(rows)} rows to {filename}")


if __name__ == "__main__":
    cli()

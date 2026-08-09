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
            if qid:
                row["qid"] = qid
            if tmdb_id:
                row["tmdb_id"] = tmdb_id


# P4947 is OPTIONAL on purpose. Requiring it meant a film with an IMDb id but
# no TMDB id matched nothing at all, so its qid could never be filled either.
_SPARQL_FIND_BY_IMDB_ID = """
SELECT ?item ?tmdb_id WHERE {
  ?item wdt:P345 "?imdb_id" .
  OPTIONAL { ?item wdt:P4947 ?tmdb_id }
}
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


def _sparql_find_film_by_imdb(imdb_id: str) -> tuple[str | None, str | None]:
    query = _SPARQL_FIND_BY_IMDB_ID.replace("?imdb_id", imdb_id)

    results = _wikidata_sparql(query)
    if not results:
        logger.warning(f"No Wikidata item for {imdb_id}")
        return None, None

    qid = results[0]["item"]["value"].replace("http://www.wikidata.org/entity/", "")
    tmdb_id = results[0].get("tmdb_id", {}).get("value")
    if not tmdb_id:
        logger.info(f"{imdb_id} resolved to {qid} but has no TMDB id")
    return qid, tmdb_id


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
    with load_csv_data(data_path / "movies.csv") as rows:
        wanted = {row["imdb_id"] for row in rows if row["imdb_id"]}
        if not wanted:
            return

        imdb_titles = _fetch_imdb_primary_titles(wanted)
        assert imdb_titles, "No IMDb titles found"
        logger.info(f"Matched {len(imdb_titles)} of {len(wanted)} IMDb ids")

        for row in rows:
            if title := imdb_titles.get(row["imdb_id"]):
                row["title"] = title


def _fetch_imdb_primary_titles(imdb_ids: set[str]) -> dict[str, str]:
    """Look up the primary title for each id in the IMDb title dump.

    The dump is ~225 MB gzipped and around 12.6 million rows, against a few
    hundred ids we care about, so keep only what was asked for and stop as
    soon as everything is found rather than materialising the whole file.
    """
    response = requests.get(
        "https://datasets.imdbws.com/title.basics.tsv.gz",
        stream=True,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    decompressed = gzip.GzipFile(fileobj=response.raw)
    textio = io.TextIOWrapper(decompressed, encoding="utf-8")
    # The dump is not quoted, and titles legitimately contain double quotes.
    csv_reader = csv.DictReader(textio, delimiter="\t", quoting=csv.QUOTE_NONE)

    titles: dict[str, str] = {}
    for row in csv_reader:
        if row["tconst"] in imdb_ids:
            titles[row["tconst"]] = row["primaryTitle"]
            if len(titles) == len(imdb_ids):
                break
    return titles


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

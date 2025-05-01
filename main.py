import csv
import gzip
import io
import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from itertools import islice
from pathlib import Path
from random import shuffle
from time import sleep

import click
import requests

from thesummermoviewager import global_leaderboard_players, playalong, player_list

logger = logging.getLogger(__name__)

CURRENT_YEAR: int = date.today().year


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
            if row["imdb_id"] == "":
                continue
            if row["qid"] != "" and row["tmdb_id"] != "":
                continue

            query = _SPARQL_FIND_BY_IMDB_ID.replace("?imdb_id", row["imdb_id"])
            sleep(1)
            r = requests.get(
                "https://query.wikidata.org/sparql",
                params={"query": query, "format": "json"},
            )
            r.raise_for_status()

            qid, tmdb_id = _sparql_find_film_by_imdb(row["imdb_id"])
            if qid and tmdb_id:
                row["qid"] = qid
                row["tmdb_id"] = tmdb_id
            else:
                logger.warning(f"Failed to find Wikidata info for {row['imdb_id']}")


_SPARQL_FIND_BY_IMDB_ID = """
SELECT ?item ?tmdb_id WHERE { ?item wdt:P345 "?imdb_id"; wdt:P4947 ?tmdb_id. }
"""


def _sparql_find_film_by_imdb(imdb_id: str) -> tuple[str, str] | tuple[None, None]:
    query = _SPARQL_FIND_BY_IMDB_ID.replace("?imdb_id", imdb_id)
    sleep(1)
    r = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
    )
    r.raise_for_status()

    if results := r.json()["results"]["bindings"]:
        qid = results[0]["item"]["value"].replace("http://www.wikidata.org/entity/", "")
        tmdb_id = results[0]["tmdb_id"]["value"]
        return qid, tmdb_id
    else:
        logger.warning(f"Failed to find Wikidata info for {imdb_id}")
        return None, None


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
@click.option("--limit", type=int, default=25)
def backfill_imdb_ids(data_path: Path, limit: int) -> None:
    with load_csv_data(data_path / "movies.csv") as rows:
        rows_missing_info = [
            row
            for row in rows
            if row["title"] != ""
            and row["year"] != ""
            and (row["imdb_id"] == "" or row["qid"] == "")
        ]
        shuffle(rows_missing_info)
        for row in islice(rows_missing_info, limit):
            qid, imdb_id = _sparql_search_by_film_title(row["title"], int(row["year"]))
            if qid and imdb_id:
                row["qid"] = qid
                row["imdb_id"] = imdb_id


_SPARQL_FILM_SEARCH_QUERY = """
SELECT DISTINCT ?item ?title ?imdb_id WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:endpoint "www.wikidata.org";
                    wikibase:api "EntitySearch";
                    mwapi:search "$TITLE";
                    mwapi:language "en".
    ?item wikibase:apiOutputItem mwapi:item.
  }
  ?item (wdt:P31/(wdt:P279*)) wd:Q11424;
    wdt:P1476 ?title;
    wdt:P577 ?date.
  FILTER((xsd:integer(YEAR(?date))) = $YEAR )
  ?item wdt:P345 ?imdb_id.
}
"""


def _sparql_search_by_film_title(
    title: str, year: int
) -> tuple[str, str] | tuple[None, None]:
    query = _SPARQL_FILM_SEARCH_QUERY.replace("$TITLE", title.replace('"', "")).replace(
        "$YEAR", str(year)
    )
    sleep(1)
    r = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
    )
    r.raise_for_status()
    results = r.json()["results"]["bindings"]
    title_matches = [r for r in results if r["title"]["value"] == title]

    if len(results) == 1:
        qid = results[0]["item"]["value"].replace("http://www.wikidata.org/entity/", "")
        imdb_id = results[0]["imdb_id"]["value"]
        return qid, imdb_id
    if len(title_matches) == 1:
        qid = title_matches[0]["item"]["value"].replace(
            "http://www.wikidata.org/entity/", ""
        )
        imdb_id = title_matches[0]["imdb_id"]["value"]
        return qid, imdb_id
    else:
        logger.warning(f"Failed to find Wikidata info for '{title}' ({year})")
        return None, None


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
@click.option("--year", type=int, default=CURRENT_YEAR)
def discover_movie_titles(data_path: Path, year: int) -> None:
    with load_csv_data(data_path / "movies.csv") as rows:
        known_movie_titles: set[str] = set(row["title"] for row in rows)

        players = global_leaderboard_players(year=year)
        shuffle(players)

        for player in islice(players, 100):
            for player_score in player_list(player=player, year=year):
                movie_title = player_score.movie
                if movie_title not in known_movie_titles:
                    logger.info(f"Adding '{movie_title}'")
                    rows.append({"year": str(year), "title": movie_title})
                    known_movie_titles.add(movie_title)


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
def discover_playalong_movies(data_path: Path) -> None:
    with load_csv_data(data_path / "movies.csv") as rows:
        known_movie_titles: set[str] = set(row["title"] for row in rows)

        for movie in playalong():
            if movie.title not in known_movie_titles:
                logger.info(f"Adding '{movie.title}'")
                rows.append(
                    {
                        "year": str(CURRENT_YEAR),
                        "title": movie.title,
                        "imdb_id": movie.imdb_id,
                        "boxofficemojo_id": movie.mojo_id,
                    }
                )
                known_movie_titles.add(movie.title)


@cli.command()
@click.argument("data-path", type=click.Path(exists=True, path_type=Path))
def fetch_imdb_titles(data_path: Path) -> None:
    response = requests.get(
        "https://datasets.imdbws.com/title.basics.tsv.gz", stream=True
    )
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
        for row in reader:
            rows.append(row)
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

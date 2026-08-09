#!/usr/bin/env python3
"""Tools for maintaining the Summer Movie Wager dataset."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from itertools import islice
from pathlib import Path
from random import shuffle
from time import sleep
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_YEAR: int = datetime.now(timezone.utc).year

TIMEOUT = 30
USER_AGENT = "summer-movie-wager-data (https://github.com/josh/summer-movie-wager-data)"

SITE = "https://thesummermoviewager.com"


def get(url: str, params: dict[str, str] | None = None) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body: str = response.read().decode(charset, errors="replace")
    return body


def get_json(url: str, params: dict[str, str] | None = None) -> Any:
    return json.loads(get(url, params))


# --- HTML ---------------------------------------------------------------
# Just enough of a tree to run the handful of queries the site needs.

VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


class Element:
    __slots__ = ("tag", "attrs", "content")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.content: list[str | Element] = []

    def attr(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def children(self) -> list[Element]:
        return [c for c in self.content if isinstance(c, Element)]

    def texts(self) -> list[str]:
        """Runs of text directly inside this element, not its descendants."""
        runs: list[str] = []
        buffer: list[str] = []
        for item in self.content:
            if isinstance(item, str):
                buffer.append(item)
            elif buffer:
                runs.append("".join(buffer))
                buffer = []
        if buffer:
            runs.append("".join(buffer))
        return runs

    def text(self, default: str = "") -> str:
        runs = self.texts()
        return runs[0] if runs else default

    def descendants(self) -> Iterator[Element]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def select(
        self,
        tag: str | None = None,
        class_: str | None = None,
        id: str | None = None,
        direct: bool = False,
    ) -> list[Element]:
        found = []
        for el in self.children if direct else self.descendants():
            if tag and el.tag != tag:
                continue
            if class_ and class_ not in el.attr("class").split():
                continue
            if id and el.attr("id") != id:
                continue
            found.append(el)
        return found


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("", {})
        self._open = [self.root]

    def _append(self, tag: str, attrs: list[tuple[str, str | None]]) -> Element:
        el = Element(tag, {k: (v or "") for k, v in attrs})
        self._open[-1].content.append(el)
        return el

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        el = self._append(tag, attrs)
        if tag not in VOID_TAGS:
            self._open.append(el)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._open) - 1, 0, -1):
            if self._open[i].tag == tag:
                del self._open[i:]
                return

    def handle_data(self, data: str) -> None:
        self._open[-1].content.append(data)


def parse_html(text: str) -> Element:
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


# --- site ---------------------------------------------------------------


@lru_cache(maxsize=1)
def available_years() -> tuple[int, ...]:
    """Years the site actually ran a wager for, read from its own year picker.

    This has to be asked for rather than assumed. Requesting a year the site
    does not have does not fail: it serves the current season's lists while
    echoing the requested year back into the page header, so `y{year}` in the
    header proves nothing. 2020 and 2021 have no wager and return 2026's data.
    """
    document = parse_html(get(f"{SITE}/index.php"))

    years: list[int] = []
    for select in document.select("select", id="year"):
        for option in select.select("option"):
            value = option.attr("value").strip()
            if value.isdigit():
                years.append(int(value))

    assert years, "no years found in year picker"
    return tuple(sorted(years))


def _assert_valid_year(year: int) -> None:
    years = available_years()
    assert year in years, f"no wager for {year}; site has {years[0]}-{years[-1]}"


@dataclass
class PlayerScore:
    player: str
    position: int
    movie: str
    score: int


def _parse_score_panels(document: Element) -> Iterator[tuple[str, list[PlayerScore]]]:
    for panel in document.select("div", class_="playerscorepanel"):
        headers = panel.select("th", class_="name")
        name = headers[0].text("").strip() if headers else ""

        picks: list[PlayerScore] = []
        for position, row in enumerate(panel.select("tr", class_="hover"), 1):
            cells = row.select("td", class_="name")
            movie = cells[0].text("").strip() if cells else ""
            results = row.select("td", class_="result")
            score_text = results[0].text("").strip() if results else ""
            score = int(score_text) if score_text.isdigit() else 0
            picks.append(PlayerScore(name, position, movie, score))
        yield name, picks


def scores(year: int) -> list[PlayerScore]:
    _assert_valid_year(year)
    document = parse_html(get(f"{SITE}/index.php", {"year": str(year)}))

    picks: list[PlayerScore] = []
    for _, panel_picks in _parse_score_panels(document):
        assert 10 < len(panel_picks) <= 13
        picks.extend(panel_picks)
    return picks


def player_list(player: str, year: int) -> list[PlayerScore]:
    _assert_valid_year(year)
    document = parse_html(
        get(
            f"{SITE}/list.php",
            {"addPlayer": player, "year": str(year), "playerScoreTable2": player},
        )
    )

    picks: list[PlayerScore] = []
    for name, panel_picks in _parse_score_panels(document):
        assert name == player, "page returned wrong player"
        assert len(panel_picks) == 13
        picks.extend(panel_picks)

    assert len(picks) == 13
    return picks


@dataclass
class PlayalongMovie:
    title: str
    imdb_id: str
    mojo_id: str


def playalong() -> list[PlayalongMovie]:
    document = parse_html(get(f"{SITE}/playalong.php"))

    imdb_ids: dict[str, str] = {}
    mojo_ids: dict[str, str] = {}
    for script in document.select("script"):
        for source in script.texts():
            if m := re.search(r"movieIdToImdbId = ({.*?});", source):
                imdb_ids = json.loads(m.group(1))
            if m := re.search(r"movieIdToMojoId = ({.*?});", source):
                mojo_ids = json.loads(m.group(1))

    movies: list[PlayalongMovie] = []
    for select in document.select("select", id="movie1"):
        for option in select.select("option", direct=True):
            title = option.attr("value").strip()
            if title:
                movies.append(PlayalongMovie(title, imdb_ids[title], mojo_ids[title]))
    return movies


# --- wikidata -----------------------------------------------------------

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

    The User-Agent is not optional. query.wikidata.org returns 403 to a
    default client UA, which is why the backfill commands silently stopped
    working and 2025 has no qid or tmdb_id.
    """
    sleep(1)
    payload = get_json(
        "https://query.wikidata.org/sparql",
        {"query": query, "format": "json"},
    )
    bindings: list[dict[str, Any]] = payload["results"]["bindings"]
    return bindings


def _sparql_find_film_by_imdb(imdb_id: str) -> tuple[str | None, str | None]:
    results = _wikidata_sparql(_SPARQL_FIND_BY_IMDB_ID.replace("?imdb_id", imdb_id))
    if not results:
        logger.warning(f"No Wikidata item for {imdb_id}")
        return None, None

    qid = results[0]["item"]["value"].replace("http://www.wikidata.org/entity/", "")
    tmdb_id = results[0].get("tmdb_id", {}).get("value")
    if not tmdb_id:
        logger.info(f"{imdb_id} resolved to {qid} but has no TMDB id")
    return qid, tmdb_id


# --- data ---------------------------------------------------------------


@contextmanager
def load_csv_data(path: Path) -> Generator[list[dict[str, str]], None, None]:
    rows: list[dict[str, str]] = []

    with path.open("r", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames
        fieldnames = list(reader.fieldnames)
        rows.extend(reader)
        logger.debug(f"Loaded {len(rows)} rows from {path}")

    yield rows

    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        logger.debug(f"Saved {len(rows)} rows to {path}")


def cmd_sort(args: argparse.Namespace) -> None:
    with load_csv_data(args.data_path / "years.csv") as rows:
        rows.sort(key=lambda row: int(row["year"]))

    with load_csv_data(args.data_path / "movies.csv") as rows:
        rows.sort(key=lambda row: (int(row["year"]), row["title"]))

    with load_csv_data(args.data_path / "lists.csv") as rows:
        rows.sort(
            key=lambda row: (int(row["year"]), row["player_name"], int(row["position"]))
        )


def cmd_backfill_wikidata_info(args: argparse.Namespace) -> None:
    with load_csv_data(args.data_path / "movies.csv") as rows:
        missing = [
            row
            for row in rows
            if row["imdb_id"] != "" and (row["qid"] == "" or row["tmdb_id"] == "")
        ]
        shuffle(missing)
        for row in islice(missing, args.limit):
            qid, tmdb_id = _sparql_find_film_by_imdb(row["imdb_id"])
            if qid:
                row["qid"] = qid
            if tmdb_id:
                row["tmdb_id"] = tmdb_id


def cmd_discover_playalong_movies(args: argparse.Namespace) -> None:
    year = str(CURRENT_YEAR)

    with load_csv_data(args.data_path / "movies.csv") as rows:
        known_titles = {(row["year"], row["title"]) for row in rows}
        known_imdb_ids = {
            (row["year"], row["imdb_id"]) for row in rows if row["imdb_id"]
        }

        for movie in playalong():
            if (year, movie.title) in known_titles:
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
            known_titles.add((year, movie.title))
            if movie.imdb_id:
                known_imdb_ids.add((year, movie.imdb_id))


def cmd_scores(args: argparse.Namespace) -> None:
    for pick in scores(args.year):
        print(f"{pick.position}. {pick.player} - {pick.movie} ({pick.score})")


def cmd_player_list(args: argparse.Namespace) -> None:
    for pick in player_list(args.player, args.year):
        print(f"{pick.position}. {pick.movie} ({pick.score})")


def cmd_play_along(args: argparse.Namespace) -> None:
    for movie in playalong():
        print(f"{movie.title} - {movie.imdb_id} - {movie.mojo_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def data_command(name: str, handler: Any) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name)
        sub.add_argument("data_path", metavar="data-path", type=Path)
        sub.set_defaults(handler=handler)
        return sub

    data_command("sort", cmd_sort)
    backfill = data_command("backfill-wikidata-info", cmd_backfill_wikidata_info)
    backfill.add_argument("--limit", type=int, default=25)
    data_command("discover-playalong-movies", cmd_discover_playalong_movies)

    sub = subparsers.add_parser("scores")
    sub.add_argument("--year", type=int, default=CURRENT_YEAR)
    sub.set_defaults(handler=cmd_scores)

    sub = subparsers.add_parser("player-list")
    sub.add_argument("player")
    sub.add_argument("--year", type=int, default=CURRENT_YEAR)
    sub.set_defaults(handler=cmd_player_list)

    sub = subparsers.add_parser("play-along")
    sub.set_defaults(handler=cmd_play_along)

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if hasattr(args, "data_path"):
        assert args.data_path.exists(), f"{args.data_path} does not exist"
    args.handler(args)


if __name__ == "__main__":
    main()

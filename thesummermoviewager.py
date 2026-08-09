import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import click
import requests
from parsel import Selector

TIMEOUT = 30

CURRENT_YEAR = datetime.now(timezone.utc).year


@lru_cache(maxsize=1)
def available_years() -> tuple[int, ...]:
    """Years the site actually ran a wager for, read from its own year picker.

    This has to be asked for rather than assumed. Requesting a year the site
    does not have does not fail: it serves the current season's lists while
    echoing the requested year back into the page header, so `y{year}` in the
    header proves nothing. 2020 and 2021 have no wager and return 2026's data.
    """
    response = requests.get(
        "https://thesummermoviewager.com/index.php", timeout=TIMEOUT
    )
    response.raise_for_status()
    selector = Selector(text=response.text)

    years: list[int] = []
    for option in selector.css("select#year option"):
        value = option.xpath("@value").get("").strip()
        if value.isdigit():
            years.append(int(value))

    assert years, "no years found in year picker"
    return tuple(sorted(years))


def _assert_valid_year(year: int) -> None:
    years = available_years()
    assert year in years, f"no wager for {year}; site has {years[0]}-{years[-1]}"


@click.group()
def cli() -> None:
    pass


@dataclass
class HostScore:
    player: str
    position: int
    movie: str
    score: int


def scores(year: int) -> list[HostScore]:
    _assert_valid_year(year)

    url = f"https://thesummermoviewager.com/index.php?year={year}"
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    selector = Selector(text=response.text)

    lists: list[HostScore] = []

    for panel_div in selector.css("div.playerscorepanel"):
        name = panel_div.css("th.name::text").get("").strip()

        pos_int = 0
        for row_tr in panel_div.css("tr.hover"):
            pos_int += 1
            movie_title = row_tr.css("td.name::text").get("").strip()
            score_str = row_tr.css("td.result::text").get("").strip()
            score: int = 0
            if score_str.isdigit():
                score = int(score_str)
            lists.append(HostScore(name, pos_int, movie_title, score))
        assert pos_int > 10 and pos_int <= 13

    return lists


@cli.command(name="scores")
@click.option("--year", type=int, default=CURRENT_YEAR)
def _scores(year: int) -> None:
    for score in scores(year):
        click.echo(f"{score.position}. {score.player} - {score.movie} ({score.score})")


@dataclass
class PlayerScore:
    player: str
    position: int
    movie: str
    score: int


def player_list(player: str, year: int) -> list[PlayerScore]:
    _assert_valid_year(year)

    url = "https://thesummermoviewager.com/list.php"
    params = {
        "addPlayer": player,
        "year": str(year),
        "playerScoreTable2": player,
    }
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    selector = Selector(text=response.text)

    lists: list[PlayerScore] = []

    for panel_div in selector.css("div.playerscorepanel"):
        name = panel_div.css("th.name::text").get("").strip()
        assert name == player, "page returned wrong player"

        pos_int = 0
        for row_tr in panel_div.css("tr.hover"):
            pos_int += 1
            movie_title = row_tr.css("td.name::text").get("").strip()
            score_str = row_tr.css("td.result::text").get("").strip()
            score: int = 0
            if score_str.isdigit():
                score = int(score_str)
            lists.append(PlayerScore(name, pos_int, movie_title, score))
        assert pos_int == 13

    assert len(lists) == 13
    return lists


@cli.command(name="player-list")
@click.argument("player")
@click.option("--year", type=int, default=CURRENT_YEAR)
def _player_list(player: str, year: int) -> None:
    for score in player_list(player, year):
        click.echo(f"{score.position}. {score.movie} ({score.score})")


def global_leaderboard_players(year: int) -> list[str]:
    assert year >= 2017, "leaderboard not available for this year"
    _assert_valid_year(year)

    url = "https://thesummermoviewager.com/index.php?globalLeaderboard"
    response = requests.get(url, params={"year": year}, timeout=TIMEOUT)
    response.raise_for_status()
    selector = Selector(text=response.text)

    players: list[str] = []
    for text in selector.css("td.mw.name::text").getall():
        players.append(text.strip())
    return players


@cli.command(name="global-leaderboard-players")
@click.option("--year", type=int, default=CURRENT_YEAR)
def _global_leaderboard_players(year: int) -> None:
    for player in global_leaderboard_players(year):
        click.echo(player)


@dataclass
class PlayalongMovie:
    title: str
    imdb_id: str
    mojo_id: str


def playalong() -> list[PlayalongMovie]:
    url = "https://thesummermoviewager.com/playalong.php"
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    selector = Selector(text=response.text)

    movie_id_to_imdb_id: dict[str, str] = {}
    movie_id_to_mojo_id: dict[str, str] = {}

    for script_text in selector.css("script::text").getall():
        if "movieIdToImdbId" in script_text and (
            m := re.search(r"movieIdToImdbId = ({.*?});", script_text)
        ):
            json_data = m.group(1)
            movie_id_to_imdb_id = json.loads(json_data)

        if "movieIdToMojoId" in script_text and (
            m := re.search(r"movieIdToMojoId = ({.*?});", script_text)
        ):
            json_data = m.group(1)
            movie_id_to_mojo_id = json.loads(json_data)

    movie_titles: list[str] = []
    for option in selector.css("#movie1 > option"):
        value = option.xpath("@value").get("").strip()
        if value:
            movie_titles.append(value)

    movies: list[PlayalongMovie] = []
    for title in movie_titles:
        imdb_id = movie_id_to_imdb_id[title]
        mojo_id = movie_id_to_mojo_id[title]
        movies.append(PlayalongMovie(title, imdb_id, mojo_id))

    return movies


@cli.command(name="play-along")
def _playalong() -> None:
    for movie in playalong():
        click.echo(f"{movie.title} - {movie.imdb_id} - {movie.mojo_id}")


if __name__ == "__main__":
    cli()

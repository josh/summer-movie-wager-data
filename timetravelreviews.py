from dataclasses import dataclass
from datetime import date, datetime

import click
import requests
from parsel import Selector

YEARS = [
    1998,
    1999,
    2000,
    2001,
    2002,
    2003,
    2004,
    2005,
    2006,
    2007,
    2008,
    2009,
    2010,
    2011,
    2012,
    2013,
    2014,
    2015,
    2016,
    2017,
    2018,
]

CURRENT_YEAR = YEARS[-1]


@click.group()
def cli() -> None:
    pass


@dataclass
class BoxOfficeScore:
    rank: int
    title: str
    release_date: date
    weeks_in_release: int
    cumulative_box_office: int


def box_office(year: int) -> list[BoxOfficeScore]:
    assert year in YEARS, "invalid year"

    url = f"http://www.timetravelreviews.com/smp/Box_Office/{year}_BoxOffice.html"
    response = requests.get(url)
    response.raise_for_status()
    selector = Selector(text=response.text)

    movies: list[BoxOfficeScore] = []

    for tr in selector.css('table[width="1100"] tr'):
        col: list[str] = []
        for td in tr.css("td"):
            text = "".join(td.css("::text").getall()).strip()
            col.append(text)
        if len(col) != 10:
            continue
        if col[0] == "Rank":
            continue
        rank = int(col[0])
        title = col[3]
        release_date = _strpdate(col[4], "%d-%b-%y") or _strpdate(col[4], "%d/%b/%y")
        weeks_in_release = int(col[5])
        cumulative_box_office = int(float(col[8][1:].replace(",", "")) * 1_000_000)
        assert release_date, f"invalid date: {col[4]}"

        movie = BoxOfficeScore(
            rank=rank,
            title=title,
            release_date=release_date,
            weeks_in_release=weeks_in_release,
            cumulative_box_office=cumulative_box_office,
        )
        movies.append(movie)

    return movies


def _strpdate(date_string: str, format: str) -> date | None:
    try:
        return datetime.strptime(date_string, format).date()
    except ValueError:
        return None


@cli.command(name="box-office")
@click.option("--year", type=int, default=CURRENT_YEAR)
def _box_office(year: int) -> None:
    for score in box_office(year):
        print(f"{score.rank}. {score.title} - ${score.cumulative_box_office}")


if __name__ == "__main__":
    cli()

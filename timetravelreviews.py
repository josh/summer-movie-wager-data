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
    release_date: date | None
    weeks_in_release: int | None
    cumulative_box_office: int


def box_office(year: int) -> list[BoxOfficeScore]:
    assert year in YEARS, "invalid year"

    url = f"http://www.timetravelreviews.com/smp/Box_Office/{year}_BoxOffice.html"
    response = requests.get(url)
    response.raise_for_status()
    selector = Selector(text=response.text)

    data: list[dict[str, str]] = []

    for table in selector.xpath("//table"):
        rows = _parse_table(table)
        if not rows:
            continue

        if len(rows[0]) == 5 and rows[0][0] == "MovieRank":
            rows[0][0] = "Rank"
            rows[0][2] = "Title"
            rows[0][3] = "Release Date"
            rows[0][4] = "Cumulative Box Office ($Millions)"

        if rows[0][0] == "Rank":
            data = _rows_to_dicts(rows)

    movies: list[BoxOfficeScore] = []
    for row in data:
        rank = int(row["Rank"])
        title = row["Title"]
        release_date = _strpdate(row["Release Date"], "%d-%b-%y") or _strpdate(
            row["Release Date"], "%d/%b/%y"
        )
        weeks_in_release: int | None = None
        if "Weeks in Release" in row:
            weeks_in_release = int(row["Weeks in Release"])
        cumulative_box_office = int(
            float(row["Cumulative Box Office ($Millions)"][1:].replace(",", ""))
            * 1_000_000
        )

        movie = BoxOfficeScore(
            rank=rank,
            title=title,
            release_date=release_date,
            weeks_in_release=weeks_in_release,
            cumulative_box_office=cumulative_box_office,
        )
        movies.append(movie)

    return movies


def _parse_table(selector: Selector) -> list[list[str]]:
    table: list[list[str]] = []
    for tr in selector.xpath(".//tr"):
        row = [
            "".join(td.xpath(".//text()").getall()).strip().replace("\t", " ")
            for td in tr.xpath("./td")
        ]
        if len(row) < 2:
            continue
        table.append(row)
    return table


def _rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


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

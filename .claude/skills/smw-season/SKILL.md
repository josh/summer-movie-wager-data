---
name: smw-season
description: Sync a Summer Movie Wager season from thesummermoviewager.com into the data branch — opening a season in spring, finalising it after Labor Day, or refilling any past year. Use when asked to import, update, finalise or re-scrape a wager year.
---

# Season sync

Everything here comes from `https://thesummermoviewager.com`. The site is the
authority on what the wager *is*; Wikidata, TMDB and Box Office Mojo are only
used to attach identifiers, which is `smw-ids`.

Work in the `data` worktree; `smw-audit` covers checking it out.

## What the site will lie to you about

Read this before scraping. Each of these has already put wrong data in this
repo at least once.

- **A year you ask for is not the year you get.** `index.php?year=2020` returns
  HTTP 200, six populated panels, and a matching `page-header y2020` class —
  serving the *current* season's lists. 2020 and 2021 have no wager. Valid
  years are exactly the options in `<select id="year">` on the homepage. Read
  them; never assume.
- **`playalong.php` ignores `?year=`.** It only ever serves the current
  season. Past playalong slates are unrecoverable.
- **`help.php` only describes the current season.** It states the exact window,
  e.g. "For the year 2026 this time period will be: 04/30/2026 - 09/07/2026".
  That is the *only* reliable source for `start_date`/`end_date`, and it is
  gone once the year turns. Capture it during the season. Do not infer dates
  from the box office chart range — that tracks the earliest tracked release,
  and it disagrees with the recorded 2024 start by seven weeks.
- **Films get retitled after the fact.** 2025's `F1` is now `F1: The Movie` and
  `From the World of John Wick: Ballerina` is now `Ballerina`. Join on
  `imdb_id`, never on title.
- **Box office positions get revised.** 2012's Prometheus is scored 7 (one spot
  away) but now reports a finishing position of 10 (two spots away). Where the
  site contradicts itself, the recorded score is the historical fact; assert no
  offset rather than "fixing" the score.
- **Tooltips use non-breaking spaces.** `Current\xa0Box\xa0Office\xa0Pos:\xa01`.
  A regex with ordinary spaces silently matches nothing. Normalise first.

## Opening a season

1. Add the `years.csv` row. Take `start_date`/`end_date` verbatim from
   `help.php`. Leave `host_winner_name` and both episode qids blank until the
   season ends.
2. Add `movies.csv` rows from the playalong feed, which carries `imdb_id` and
   `boxofficemojo_id` already. Title comes from the feed — the wager's own name
   for a film is canonical here, not IMDb's.
3. Add the six host lists to `lists.csv`, 13 picks each, keyed on `imdb_id`.
4. Watch for one film's id appearing twice in the feed. In 2026 it gave
   "Fall 2" the id for "Animal Farm". Resolve by hand; never import both.

## Closing a season

After the end date in `years.csv`:

1. Refetch scores. A blank result cell means **0** for a finished season, but
   **unknown** for a live one — an unreleased film shows a release date there,
   not a number.
2. Fill `offset` from each row's box office position. It is defined only for
   the ten ordered picks that landed in the Top 10; dark horses are unordered.
3. Set `host_winner_name` to the top scorer, and cross-check it against
   `index.php?trivia`, which states the winner outright.
4. The results episode usually appears on Wikidata some weeks later. Leave
   `results_episode_qid` blank until it exists.

## Scoring

| outcome | points |
|---|---|
| pick for #1 or #10 exactly right | 13 |
| picks #2–#9 exactly right | 10 |
| one spot away | 7 |
| two spots away | 5 |
| anywhere else inside the Top 10 | 3 |
| dark horse (11–13) inside the Top 10 | 1 |
| outside the Top 10 | 0 |

`offset` is `abs(position - actual)`. Every value written must satisfy this
table against its score — `validate.sql` enforces it.

## Extraction

Fetch with a descriptive User-Agent and cache to a file; pages are ~240 KB and
you will want to re-parse without refetching.

```bash
curl -s -A "summer-movie-wager-data (https://github.com/josh/summer-movie-wager-data)" \
  "https://thesummermoviewager.com/index.php?year=2026" -o /tmp/smw2026.html
```

Valid years:

```python
re.findall(r'<option value="(\d{4})"', re.search(r'<select[^>]*id="year".*?</select>', h, re.S).group(0))
```

Playalong slate — the data is JSON in a `<script>`, so no HTML parsing:

```python
imdb = json.loads(re.search(r'movieIdToImdbId = ({.*?});', h).group(1))
mojo = json.loads(re.search(r'movieIdToMojoId = ({.*?});', h).group(1))
titles = [t for t in re.findall(r'<option value="([^"]*)"', re.search(r'id="movie1".*?</select>', h, re.S).group(0)) if t]
```

Score panels — split on the panel class, then read rows. Verified to reproduce
all 1232 picks across 20 seasons:

```python
for chunk in h.split('playerscorepanel')[1:]:
    name = html.unescape(re.search(r'<th class="mw name"[^>]*>(.*?)<', chunk).group(1)).strip()
    for position, row in enumerate(re.finditer(r'<tr class="mw hover"[^>]*>(.*?)</tr>', chunk, re.S), 1):
        body  = row.group(1)
        movie = html.unescape(re.search(r'<td class="mw name"[^>]*>(.*?)</td>', body, re.S).group(1)).strip()
        score = html.unescape(re.search(r'<td class="mw result[^"]*"[^>]*>(.*?)</td>', body, re.S).group(1)).strip()
```

Actual finishing position, for `offset`, lives in the row's tooltip:

```python
title  = html.unescape(re.search(r'<tr class="mw hover"[^>]*title="([^"]*)"', row_html).group(1)).replace('\xa0', ' ')
actual = int(re.search(r'Box Office Pos:\s*(\d+)', title).group(1))
```

Classes are token lists (`class="mw name"`), so match `mw name`, not `name`.

## Before handing anything back

Two things, always.

**Diff against what is already known.** Before writing a season, re-extract a
season already in the data and check it matches `lists.csv` exactly. If an
extractor is wrong, that is where it shows up — not in the new year, where
nothing can contradict it.

**Run the validation.** From the data directory,
`sqlite3 -bail :memory: < validate.sql`. It must exit 0. CI does not do this;
it is your job. See `smw-audit`.

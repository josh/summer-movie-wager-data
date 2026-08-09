---
name: smw-audit
description: Check the Summer Movie Wager data branch before handing it back, and review a table in depth for errors the schema cannot catch. Use after any change to years.csv, movies.csv or lists.csv, and whenever asked to audit or review the dataset.
---

# Auditing the data

There is no CI on the data branch. Nothing will catch a bad edit except this.
Run it after every change, before every push.

```
just validate
# or, from the data directory
sqlite3 -bail :memory: < validate.sql
```

Exit 0 and a line like `ok: 18 years, 983 movies, 1076 list rows` means the
structure and the game's rules both hold. Anything else aborts non-zero.

## Reading a failure

`validate.sql` loads the CSVs into a real schema, so most failures name the
constraint directly.

| message | meaning |
|---|---|
| `FOREIGN KEY constraint failed` | a `lists.csv` row points at a film that does not exist for that year |
| `UNIQUE constraint failed: movies.year, movies.imdb_id` | the same film twice in one season |
| `CHECK constraint failed: score IS NULL OR score IN (...)` | a score outside 0, 1, 3, 5, 7, 10, 13 |
| `CHECK constraint failed: position <= 10 OR ...` | a dark horse scored as an ordered pick |
| `CHECK constraint failed: n = 0` | one of the assertions at the foot of the file — read the line number to see which |

The assertions cover 13 picks per player, contiguous positions, no film picked
twice by one player, offset agreeing with score, every year declared in
`years.csv`, the winner being the top scorer once a season is fully scored, and
each file being sorted.

Sortedness failures are fixed with `just sort`, not by hand.

## Known exceptions

**2012 short lists.** Alex Albrecht has 12 picks and Jeff Cannata 11. The site
records them that way, so the shortfall is upstream. Exempted by name in
`validate.sql`. Do not "fix" it.

**2012 Prometheus has no offset.** The site scores it 7, meaning one spot away,
but now reports its finishing position as 10, meaning two. Its box office data
was revised after the fact. The recorded score is the historical fact, so no
offset is asserted.

**Blank is not always missing.** Dark horses have no offset because they are
unordered. Films outside the Top 10 have no offset. A live season has no
scores yet. `budget` and `box_office_end_date` are empty on every row.

## Going deeper than the schema

For a real review, check things `validate.sql` cannot:

- **Winners against the site.** `index.php?trivia` states each season's winner
  outright, and also records that 2020 and 2021 had no wager ("Winner:
  COVID-19"). All 17 recorded winners have been confirmed this way.
- **Scores against the site.** Re-extract a finished season and compare; 971 of
  972 matched when this was last done, and the single disagreement was a real
  error — a dark horse that placed 9th and was recorded as 0 instead of 1.
- **Identifier coverage by year.** A column that is complete everywhere except
  one span usually means a source only ever covered the current season, which
  is true of the playalong feed.
- **Fields that are empty everywhere.** `budget` and `box_office_end_date` are
  0% across all rows, and `box_office_gross` is absent for 2019 and 2022–2026.

## Before handing anything back

State what changed, what you verified, and what you deliberately left blank.
A blank that was a judgement call is worth naming; a wrong value that looked
plausible is the outcome this dataset cannot absorb.

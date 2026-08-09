---
name: smw-ids
description: Fill or verify external identifiers on the Summer Movie Wager dataset — imdb_id, tmdb_id, qid and boxofficemojo_id — from Wikidata, TMDB and Box Office Mojo. Use when rows are missing ids, when an id looks wrong, or when new films have been added.
---

# Identifier resolution

No HTML parsing is needed here. Wikidata and TMDB are JSON APIs; Box Office
Mojo needs one regex.

## The rule that matters most

**Never propose an id from memory.** In one sitting on this dataset that
produced wrong ids for Day Watch (resolved to *Poseidon*), Knight & Day
(*Star Trek*), Sicario 2 (*12th Man*) and Mr. Chibbs. Across a batch of 58
proposed from recall, 33 failed verification.

Supply the *corrected spelling* — which is checkable by eye — and let the
source supply the id.

```
Idelwild                          -> Idlewild
A Perfect Getwaway                -> A Perfect Getaway
Straight Out of Compton           -> Straight Outta Compton
The Dangerous Lives of Alter Boys -> ...Altar Boys
Rise of the Planet of Apes        -> Rise of the Planet of the Apes
```

## Verify by label, not by year

A year check passes wrong answers. All three bad ids above landed within a
year of the target. Compare the resolved **label** to the title you asked for;
that is what catches them.

Where several candidates share a title and year, disambiguate with the row's
own `box_office_start_date`. The Believer's stored `2002-05-17` matches
tt0247199 exactly; Journey to the Center of the Earth's `2008-07-11` picks the
Brendan Fraser release over two same-year retellings.

If nothing separates the candidates, **leave the field empty**. A blank is
recoverable; a plausible wrong id is not.

## Collision check before writing

Every time, without exception:

- no `(year, imdb_id)` pair twice in `movies.csv`
- no `boxofficemojo_id` claimed by two films
- an id that already exists for that year means you have found a **duplicate
  row**, not a gap — merge them, keeping the box office from one and the ids
  from the other

This check found four duplicate rows in this dataset, including one created
minutes earlier by a near-duplicate guard whose cutoff was slightly too tight.

## Wikidata

Needs a descriptive User-Agent. The default client UA gets 403, which is why
these backfills silently did nothing for a year and 2025 arrived with no qids.

```python
UA = "summer-movie-wager-data (https://github.com/josh/summer-movie-wager-data)"
url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
```

Batch with `VALUES` rather than looping — 58 ids resolve in one request.
`P345` is IMDb, `P4947` TMDB, `P577` publication date.

```sparql
SELECT ?imdb ?item ?itemLabel ?pub WHERE {
  VALUES ?imdb { "tt0373889" "tt0449088" }
  ?item wdt:P345 ?imdb .
  OPTIONAL { ?item wdt:P4947 ?tmdb }
  OPTIONAL { ?item wdt:P577 ?pub }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
```

Keep `P4947` optional. Requiring it means a film with an IMDb id but no TMDB
id matches nothing, so its qid can never be filled either.

**Wikidata cannot supply `boxofficemojo_id`.** It has near-complete coverage
under P1237, but that is the retired slug scheme (`harrypotter5`). Every
property with a boxofficemojo formatter URL is marked former or archived. Do
not go looking again.

## TMDB

`TMDB_API_KEY` must be in the environment.

The `find` endpoint keyed on an IMDb id is an exact external-id lookup with
nothing to disambiguate — 400 rows filled this way, validated 30/30 against
known values first.

```
https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id&api_key=$TMDB_API_KEY
  -> movie_results[0].id
```

Going the other way — search by title, then read back `external_ids` — is how
to resolve a film that has no IMDb id yet. That path *is* ambiguous, so apply
the label and date checks above.

## Box Office Mojo

The dataset stores the modern release id (`rl…`). Fetch the title page and
take the id from the **weekend** link, which belongs to the film's own
domestic run:

```python
re.search(r'/release/(rl\d+)/weekend', page).group(1)
```

Do **not** take the first anchor labelled "Domestic". Title pages list related
releases alongside the film's own, which produces impossible results: one id
claimed by both Men in Black II and Spider-Man, another by both Spider-Man 2
and Spider-Man 3. The weekend link resolved 797 of 823 with no collisions; the
Domestic anchor managed 628 with two.

Be polite — roughly a second between requests, and cache pages to disk so
re-parsing costs nothing.

A film with no domestic release recorded simply has no id. Leave it blank.

## Before handing anything back

Validate a sample against rows that already have the field. This is what
proved each method before it was trusted: 30/30 for TMDB, 135 of 154 for Box
Office Mojo with **zero** disagreements. Then run `just validate`.

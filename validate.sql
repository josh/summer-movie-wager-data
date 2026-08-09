-- Validate the Summer Movie Wager CSVs.
-- Run from the directory holding them:
--
--   sqlite3 -bail :memory: < validate.sql

PRAGMA foreign_keys = ON;

-- Text first, so empty CSV fields can become NULL rather than ''.
CREATE TABLE raw_years  (year TEXT, start_date TEXT, end_date TEXT, host_winner_name TEXT, wager_episode_qid TEXT, results_episode_qid TEXT);
CREATE TABLE raw_movies (year TEXT, title TEXT, imdb_id TEXT, boxofficemojo_id TEXT, tmdb_id TEXT, qid TEXT, budget TEXT, box_office_start_date TEXT, box_office_end_date TEXT, box_office_gross TEXT);
CREATE TABLE raw_lists  (year TEXT, player_name TEXT, imdb_id TEXT, movie_title TEXT, position TEXT, "offset" TEXT, score TEXT);

.mode csv
.import --skip 1 years.csv raw_years
.import --skip 1 movies.csv raw_movies
.import --skip 1 lists.csv raw_lists

.read schema.sql

INSERT INTO years SELECT CAST(year AS INTEGER), nullif(start_date,''), nullif(end_date,''),
       nullif(host_winner_name,''), nullif(wager_episode_qid,''), nullif(results_episode_qid,'') FROM raw_years;

INSERT INTO movies SELECT CAST(year AS INTEGER), title, nullif(imdb_id,''), nullif(boxofficemojo_id,''),
       nullif(tmdb_id,''), nullif(qid,''), nullif(budget,''), nullif(box_office_start_date,''),
       nullif(box_office_end_date,''), nullif(box_office_gross,'') FROM raw_movies;

INSERT INTO lists SELECT CAST(year AS INTEGER), player_name, nullif(imdb_id,''), movie_title,
       CAST(position AS INTEGER), nullif("offset",''), nullif(score,'') FROM raw_lists;

-- Each assertion counts violations into a table that accepts only zero.

-- 2012 is exempt: the site itself records Alex Albrecht with 12 picks and
-- Jeff Cannata with 11.
CREATE TABLE assert_list_length (n INTEGER CHECK (n = 0));
INSERT INTO assert_list_length
SELECT count(*) FROM (
    SELECT year, player_name FROM lists
    WHERE NOT (year = 2012 AND player_name IN ('Alex Albrecht', 'Jeff Cannata'))
    GROUP BY 1,2 HAVING count(*) <> 13);

CREATE TABLE assert_positions_contiguous (n INTEGER CHECK (n = 0));
INSERT INTO assert_positions_contiguous
SELECT count(*) FROM (SELECT year, player_name FROM lists GROUP BY 1,2
                      HAVING max(position) <> count(*) OR min(position) <> 1);

CREATE TABLE assert_no_repeat_pick (n INTEGER CHECK (n = 0));
INSERT INTO assert_no_repeat_pick
SELECT count(*) FROM (SELECT year, player_name, imdb_id FROM lists
                      WHERE imdb_id IS NOT NULL GROUP BY 1,2,3 HAVING count(*) > 1);

CREATE TABLE assert_offset_matches_score (n INTEGER CHECK (n = 0));
INSERT INTO assert_offset_matches_score
SELECT count(*) FROM lists
WHERE "offset" IS NOT NULL AND score IS NOT NULL
  AND score <> CASE
        WHEN "offset" = 0 AND position IN (1, 10) THEN 13
        WHEN "offset" = 0 THEN 10
        WHEN "offset" = 1 THEN 7
        WHEN "offset" = 2 THEN 5
        ELSE 3 END;

CREATE TABLE assert_years_declared (n INTEGER CHECK (n = 0));
INSERT INTO assert_years_declared
SELECT count(*) FROM (SELECT DISTINCT year FROM lists EXCEPT SELECT year FROM years);

CREATE TABLE assert_winner_is_top_scorer (n INTEGER CHECK (n = 0));
INSERT INTO assert_winner_is_top_scorer
SELECT count(*) FROM (
  SELECT y.year FROM years y
  JOIN (SELECT year, player_name, sum(score) AS pts FROM lists GROUP BY 1,2) t ON t.year = y.year
  WHERE y.host_winner_name IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM lists WHERE year = y.year AND score IS NULL)
  GROUP BY y.year
  HAVING max(pts) <> max(CASE WHEN t.player_name = y.host_winner_name THEN pts END)
);

-- raw_* rowids preserve file order, so compare against the sorted position.
CREATE TABLE assert_years_sorted (n INTEGER CHECK (n = 0));
INSERT INTO assert_years_sorted
SELECT count(*) FROM (
    SELECT rowid AS pos, row_number() OVER (ORDER BY CAST(year AS INTEGER)) AS want
    FROM raw_years) WHERE pos <> want;

CREATE TABLE assert_movies_sorted (n INTEGER CHECK (n = 0));
INSERT INTO assert_movies_sorted
SELECT count(*) FROM (
    SELECT rowid AS pos, row_number() OVER (ORDER BY CAST(year AS INTEGER), title) AS want
    FROM raw_movies) WHERE pos <> want;

CREATE TABLE assert_lists_sorted (n INTEGER CHECK (n = 0));
INSERT INTO assert_lists_sorted
SELECT count(*) FROM (
    SELECT rowid AS pos,
           row_number() OVER (ORDER BY CAST(year AS INTEGER), player_name, CAST(position AS INTEGER)) AS want
    FROM raw_lists) WHERE pos <> want;

SELECT 'ok: ' || (SELECT count(*) FROM years)  || ' years, '
               || (SELECT count(*) FROM movies) || ' movies, '
               || (SELECT count(*) FROM lists)  || ' list rows';

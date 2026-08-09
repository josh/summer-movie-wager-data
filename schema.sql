-- Schema for the Summer Movie Wager CSVs.
-- Loaded and checked by validate.sql.

CREATE TABLE years (
    year                INTEGER PRIMARY KEY,
    start_date          TEXT CHECK (start_date IS NULL OR start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    end_date            TEXT CHECK (end_date   IS NULL OR end_date   GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    host_winner_name    TEXT,
    wager_episode_qid   TEXT CHECK (wager_episode_qid   IS NULL OR wager_episode_qid   GLOB 'Q[0-9]*'),
    results_episode_qid TEXT CHECK (results_episode_qid IS NULL OR results_episode_qid GLOB 'Q[0-9]*'),
    CHECK (start_date IS NULL OR end_date IS NULL OR start_date < end_date)
);

CREATE TABLE movies (
    year                  INTEGER NOT NULL,
    title                 TEXT    NOT NULL,
    imdb_id               TEXT CHECK (imdb_id          IS NULL OR imdb_id          GLOB 'tt[0-9]*'),
    boxofficemojo_id      TEXT CHECK (boxofficemojo_id IS NULL OR boxofficemojo_id GLOB 'rl[0-9]*'),
    tmdb_id               INTEGER,
    qid                   TEXT CHECK (qid              IS NULL OR qid              GLOB 'Q[0-9]*'),
    budget                INTEGER,
    box_office_start_date TEXT,
    box_office_end_date   TEXT,
    box_office_gross      INTEGER,
    PRIMARY KEY (year, title)
);
CREATE UNIQUE INDEX movies_year_imdb ON movies (year, imdb_id);

CREATE TABLE lists (
    year        INTEGER NOT NULL,
    player_name TEXT    NOT NULL,
    imdb_id     TEXT,
    movie_title TEXT    NOT NULL,
    position    INTEGER NOT NULL CHECK (position BETWEEN 1 AND 13),
    "offset"    INTEGER CHECK ("offset" IS NULL OR "offset" >= 0),
    score       INTEGER CHECK (score IS NULL OR score IN (0, 1, 3, 5, 7, 10, 13)),
    PRIMARY KEY (year, player_name, position),
    FOREIGN KEY (year, imdb_id) REFERENCES movies (year, imdb_id),
    CHECK ("offset" IS NULL OR position <= 10),
    CHECK (position <= 10 OR score IS NULL OR score IN (0, 1))
);

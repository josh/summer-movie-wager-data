default: lint validate

# Check out the data branch as a worktree at ./data if it is not already there.
data:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -e data ] && exit 0
    git fetch --quiet origin data
    git show-ref --verify --quiet refs/heads/data || git branch --track data origin/data
    git worktree add data data

lint:
    uv run ruff format --diff .
    uv run ruff check .
    uv run mypy .

validate: data
    cd data && sqlite3 -bail :memory: < validate.sql

sort: data
    uv run python main.py sort data/

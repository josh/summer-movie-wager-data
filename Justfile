default: validate

data:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -e data ] && exit 0
    git fetch --quiet origin data
    git show-ref --verify --quiet refs/heads/data || git branch --track data origin/data
    git worktree add data data

validate: data
    cd data && sqlite3 -bail :memory: < validate.sql

sort: data
    ./main.py sort data/

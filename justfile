# Template development. `just` lists recipes.

default:
    @just --list

# Render the template in several configurations and run each result's checks
test:
    uv run --quiet pytest -q

# Render into a scratch directory for manual inspection
render dest="/tmp/okf-kb-preview" *args:
    rm -rf {{dest}}
    uv run --quiet copier copy --trust --defaults --vcs-ref=HEAD {{args}} . {{dest}}

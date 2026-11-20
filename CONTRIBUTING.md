# Contributing

## Rules for every change

1. Work on a branch: `git switch -c fix-awards-2025`. Keep `main` working.
2. One change per commit, with a clear subject in the imperative: `Parse the new awards table layout`.
3. Run `pytest -q` before each push. CI runs the same tests on Windows and Linux.
4. Open a pull request, wait for a green check, then merge it (squash).
5. Never commit `data/`, `.sqlite` files, logs, proxy passwords or other secrets (`.gitignore` covers the first three).

## When the site changes

The site changes its HTML without notice. A parser that suddenly finds no rows is the usual sign.

1. Save the new page: `tnmsc-scraper crawl --only blacklist`, then copy the page body from `data\tnmsc.sqlite`
   (table `pages`), or save it from the browser.
2. Put it in `tests/pages/` with a clear name, for example `tnmsc-blacklist-2026-12.html`. Trim it to a few rows.
3. Write a failing test in `tests/test_parse.py`, then fix `parse.py`.
4. Keep `parse.py` pure: no network, no files, no clock. The same HTML gives the same records.

## Rate limits and stops are not optional

- Do not lower the default `--delay` (3 s) or remove the jitter.
- Do not add parallel requests.
- Every new loop that makes requests goes through `Fetcher`, so all limits and the STOP file still work.
- A new limit needs a test with the fake clock and the fake transport in `tests/conftest.py` (no network in tests).

## Adding a new page

1. Add the URL to the page list in `parse.py` (`url_of`) and a parser function.
2. Give each record a stable id (the site's own number where there is one), so a rerun updates instead of duplicating.
3. Add a fixture and a test.
4. Add the page to the table in `README.md` and a line to `CHANGELOG.md`.

## Bugs

Open an issue with: the command you ran, the last 30 lines of `data\logs\tnmsc-scraper.log`, the exit code, and the
page URL. If the problem is a page, attach the saved HTML.

## Style

- Python 3.10+, standard library and `requests` only, unless a new dependency saves a lot of code.
- `pathlib` for paths, UTF-8 for every file (Windows needs `encoding="utf-8"`).
- Short functions, a docstring that says what comes in and what goes out, a comment only for a reason the code cannot show.

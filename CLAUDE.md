# Notes for AI coding assistants (Claude Code and others)

This repo scrapes public pages of the Tamil Nadu Medical Services Corporation. The owner works on Windows (PowerShell)
and on a Linux box. Read `README.md` and `CONTRIBUTING.md` first.

## Hard rules

- Passive collection only: what a normal visitor's browser gets. No logins, OTPs or captchas, no guessing of hidden URLs,
  no scanning or probing of the server.
- Never weaken the limits in `fetch.py` (delay, jitter, one request at a time, max requests, max time, max bytes,
  stop after refusals or errors, Retry-After, STOP file, Ctrl-C). New request loops go through `Fetcher`.
- Tests never touch the network: use the fake clock and fake transport in `tests/conftest.py`.
- Keep `parse.py` pure and test every parser change on a saved page in `tests/pages/`.
- No secrets in the repo (proxy URLs with passwords, tokens). Use environment variables.
- Commits are the owner's: no "Co-Authored-By" trailer and no "Generated with" line in commits or pull requests.
- Do not put names of officials or private individuals in reports made from this data.

## Commands

```
pip install -e ".[test]"
pytest -q
python -m tnmsc_scraper crawl --only blacklist --max-requests 3 --out data-test
python -m tnmsc_scraper status --out data-test
```

A smoke run against the real site stays small: `--max-requests 3` or less.

## Layout

- `tnmsc_scraper/parse.py`: parsers and the page list (`url_of`).
- `tnmsc_scraper/fetch.py`: `Limits`, `Fetcher`, `StopRun`; `USER_AGENT` names the project.
- `tnmsc_scraper/store.py`: SQLite tables `pages`, `records` (upsert by id; first_seen, last_seen, changed_at), `runs`.
- `tnmsc_scraper/cli.py`: `crawl`, `export`, `status`.

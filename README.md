# tnmsc-scraper

A polite scraper for the public pages of the Tamil Nadu Medical Services Corporation (TNMSC, https://tnmsc.tn.gov.in).
It collects the blacklists, the drug rate contracts (with each firm's bid), the equipment rate contracts, the award
lists and the tender notifications, and keeps them in one SQLite file that you can export to CSV.

It runs on Windows, macOS and Linux. It does not need any server or account.

## What it collects

| `--only` value | Page | Records |
|---|---|---|
| `blacklist` | Blacklisted firms and items (drug and equipment) | firm, product, reason, from, to, NSQ flag |
| `drugrc` | Drug rate contracts, one page per tender (T23002, T25048, ...) | drug, unit, L1 rate, each firm's bid |
| `equipmentrc` | Equipment, furniture, linen, reagents rate contracts | item, make/model, rate, firm |
| `awards` | Award lists by year | tender, firm, value, PDF link |
| `notifications` | Tender notifications by year | tender, dates, PDF link |

`--docs` also downloads the PDFs that these pages link (off by default; about 924 award PDFs).

## Install (Windows, PowerShell)

```powershell
git clone https://github.com/insightLegion/tnmsc-scraper.git
cd tnmsc-scraper
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

On macOS or Linux, use `python3 -m venv .venv` and `source .venv/bin/activate`.

## Run

```powershell
tnmsc-scraper crawl                          # all list pages, about 31 requests, about 2.5 minutes
tnmsc-scraper crawl --only blacklist         # one kind of page
tnmsc-scraper crawl --docs --max-requests 1000   # also the PDFs (only new ones on later runs)
tnmsc-scraper status                         # last runs, counts per kind
tnmsc-scraper export --csv exports           # one CSV per record kind
```

`python -m tnmsc_scraper ...` works the same way. Data goes to `data\` (`--out` changes it):
`data\tnmsc.sqlite`, `data\logs\tnmsc-scraper.log`, `data\docs\...`.

The CSV files are UTF-8 with a BOM, so Excel shows Tamil text correctly. A list in a cell is JSON text.

## Limits and stops

The defaults are safe for a small government server. Change them with these flags:

| Flag | Default | What it does |
|---|---|---|
| `--delay`, `--jitter` | 3 s, 0-2 s | Wait between two requests. One request at a time. |
| `--max-requests`, `--max-per-host` | 300, 300 | Stop after this many requests. |
| `--max-minutes` | 30 | Stop after this run time. |
| `--max-mb`, `--max-file-mb` | 500, 50 | Stop after this many MB; skip a file larger than this. |
| `--max-refusals` | 5 | Stop after 5 refusals in a row (403, 429, 503). The wait doubles before each retry: 10, 20, 40, 80 s. |
| `--max-errors` | 5 | Stop after 5 errors in a row (no answer, timeout, 5xx). |
| `--timeout` | 60 s | Time limit for one request. |

Also:

- The scraper obeys `Retry-After`. A `Retry-After` of more than 300 s stops the run.
- A file named `STOP` in the current folder or in `--out` ends the run within half a second. In PowerShell: `New-Item STOP`.
  Delete the file before the next run.
- The first Ctrl-C finishes the current request, saves the state and exits. A second Ctrl-C quits at once.
- Exit codes: 0 = finished, 2 = stopped early (limit, STOP file, Ctrl-C), 1 = bad arguments or a program error.

Raise `--delay` if the site gets slow or answers 403. Do not lower it below 2 s.

## From outside India

The site may not answer from outside India. Use an Indian proxy: `--proxy http://user:pass@host:port`, or set
`HTTPS_PROXY`. Some Indian government servers do not send their intermediate certificates; if TLS fails, pass
`--ca-bundle file.pem` with the missing certificate added.

## Known site quirks

- The list pages send no `ETag` or `Last-Modified`, so every run downloads them again (31 pages; small).
- Drug tender `t21083` is empty now. The run logs a warning and continues.
- `edl2024`, `T19062` and `t18036` answer "Invalid URL", so they are not in the page list.
- The notifications pages for 2025 and 2026 show the 2026-27 list (a fault on the site).
- Bidders and prices of the awards are only in the award PDFs. This tool does not parse PDFs yet.
- Records that disappear from the site stay in the database; `last_seen` shows the last run that saw them.

## Project files

- `tnmsc_scraper/parse.py`: pure parsers, tested on saved pages in `tests/pages/`.
- `tnmsc_scraper/fetch.py`: the HTTP client, the rate limit and the hard stops.
- `tnmsc_scraper/store.py`: SQLite (`pages`, `records`, `runs`) and CSV export.
- `tnmsc_scraper/cli.py`: the commands.
- `CONTRIBUTING.md`: how to change it. `CLAUDE.md`: notes for AI coding assistants. `CHANGELOG.md`: versions.

## Use of the data

The pages are public. Collect only what a normal visitor sees: no logins, no captchas, no load the site cannot carry.
Names of officials on these pages are public data, but do not put them in published reports.

## License

MIT (see `LICENSE`). The parsers come from the s1d-labs `medical-procurement` scraper family.

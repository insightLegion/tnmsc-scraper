# Changelog

## 0.1.0 (21 Nov 2026)

- First version: blacklist, drug rate contracts (with each firm's bid), equipment rate contracts, awards and
  notifications pages; optional PDF download.
- Polite client: 3 s delay with jitter, one request at a time, conditional GET, Retry-After.
- Hard stops: max requests, max requests per host, max time, max MB, max file size, refusals and errors in a row with
  back-off, STOP file, clean Ctrl-C.
- SQLite store with upsert and run history; CSV export (UTF-8 with BOM).
- Tests for parsers, limits, stops, store and CLI; CI on Windows and Linux.
- Smoke run (21 Nov 2026): 1 request, 95 blacklist records.

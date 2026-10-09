# Project knowledge

Full context lives in [knowledge.md](knowledge.md). Development rules live in [VOWS.md](VOWS.md). Read both before starting work.

## Quickstart
- Current client: Adobe Flash Player projector (`MKO_Client/flash-projector/flashplayer363.exe`). Vite is not in use and `client/` is not in this checkout.
- Setup: none beyond the Python 3 standard library (plus Pillow for captcha only).
- Dev: from `Server-v1/`, run `python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080`.
- Test: from `Server-v1/`, run `python3 -m unittest discover -s tests` (63 tests); from `tools/`, `python3 -m unittest discover -s tests` (25 tests).
- Legacy data: `python3 tools/migrate_mysql_to_sqlite.py --users stress` copies only the named account's rows into SQLite (see [docs/mysql-to-sqlite-migration.md](docs/mysql-to-sqlite-migration.md)).

## Architecture
- Key directories: `Server-v1/` (Python game and web server), `tools/` (projector launcher and reverse-engineering helpers), `docs/` (protocol, boot chain, parity audit), `reference/TonNgoKhong/` (legacy game distribution, do not modify binaries).
- Data flow: the Flash projector calls the web API on `:8080` for login, then connects its game socket to `:8008`. See `knowledge.md` for the diagram.

## Conventions
- Formatting/linting: none configured. Keep docstrings to 1–2 sentences.
- Patterns to follow: test protocol changes with seeded data and real client replies. The Java server is the behavioral oracle.
- Things to avoid: putting passwords in URLs, exposing the server to the internet, reintroducing plaintext passwords or unsanitized SQL, hand-editing binary game tables, and committing runtime state (`data/`, logs, pid files).
- Process rule: start or stop server, projector, or preview processes only when the user asks.

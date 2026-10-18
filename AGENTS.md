# Project knowledge

Full context lives in [knowledge.md](knowledge.md). Development rules live in [VOWS.md](VOWS.md). Read both before starting work.

## Quickstart
- Current client: Adobe Flash Player projector (`MKO_Client/flash-projector/flashplayer363.exe`). Vite is not in use and `client/` is not in this checkout.
- Setup: none beyond the Python 3 standard library (plus Pillow for captcha only).
- Dev: from `Server-v1/`, run `python3 server.py --db data/mko.db --game 127.0.0.1:8008 --web 127.0.0.1:8080`.
- Test: from `Server-v1/`, run `python3 -m unittest discover -s tests` (837 tests); from `tools/`, `python3 -m unittest discover -s tests` (44 tests).
- Legacy data: `python3 tools/migrate_mysql_to_sqlite.py --users stress` copies only the named account's rows into SQLite (see [docs/mysql-to-sqlite-migration.md](docs/mysql-to-sqlite-migration.md)).

## Architecture
- Key directories: `Server-v1/` (Python game and web server), `tools/` (projector launcher and reverse-engineering helpers), `docs/` (protocol, boot chain, parity audit), `reference/TonNgoKhong/` (legacy game distribution, do not modify binaries).
- Data flow: the Flash projector calls the web API on `:8080` for login, then connects its game socket to `:8008`. See `knowledge.md` for the diagram.

## Conventions
- Formatting/linting: none configured. Keep docstrings to 1–2 sentences.
- Patterns to follow: test protocol changes with seeded data and real client replies. The Java server is the behavioral oracle.
- Things to avoid: putting passwords in URLs, exposing the server to the internet, reintroducing plaintext passwords or unsanitized SQL, hand-editing binary game tables, and committing runtime state (`data/`, logs, pid files).
- Process rule: start or stop server, projector, or preview processes only when the user asks.

<!-- BEGIN brain.md -->
## Project Brain

This project keeps a **Project Brain**: a persistent memory layer of its durable decisions, requirements, and constraints. Read `./BRAIN.md` for the full read/write contract.

The `brain` CLI is not guaranteed to be on `PATH`. From the project root, invoke it as `node <brain-page-skill-dir>/bin/brain.mjs <subcommand> [flags]`, resolving `<brain-page-skill-dir>` to the installed `brain-page` skill directory.

Maintain the brain as part of normal coding work — not as a separate task. While discussing or implementing features:
- **Start of a task:** load relevant context with the `brain` CLI (`list-pages`, `read-page`, `read-root`). Prefer a narrow read over scanning everything.
- **When a decision, requirement, constraint, or durable insight settles** (in chat or while coding): capture it immediately via the `brain` CLI. Do not wait to be asked and do not batch it for later.
- **Pure implementation with no new decision:** do not write to the brain.
- **When overturning a prior conclusion:** update the page (`update-truth` and/or `append-timeline` with `kind: reversal`, or `archive-page`).
- Only store what will still matter in six months and is hard to reconstruct from the code alone.
- Never hand-edit brain files. If a brain MCP server is connected and authenticated, prefer it; otherwise use the `brain` CLI.

The brain skills (`brain-setup`, `brain-page`, `brain-ingest`, `brain-bootstrap`) are installed in your global skills directory. To scaffold a new project, run `node <brain-page-skill-dir>/bin/brain.mjs init` from its root.

If native notes/history are available, keep relevant brain page IDs and unresolved task state in notes; search history for earlier task evidence. After context rollover, re-read relevant pages through the CLI for current project facts. Do not copy task history into the brain.
<!-- END brain.md -->

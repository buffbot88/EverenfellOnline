# MySQL → SQLite migration

The Python server keeps its state in SQLite (`Server-v1/data/mko.db`). The legacy
Java stack keeps the same state in MySQL (`caonima.account`, `dntg.user_role`,
`dntg.role_stage`, `dntg.role_account`). This document records what is moved,
what is deliberately left behind, and the traps found while doing it.

Tool: [tools/migrate_mysql_to_sqlite.py](../tools/migrate_mysql_to_sqlite.py).
MySQL is only ever read; nothing in the legacy database is modified.

```
python3 tools/migrate_mysql_to_sqlite.py --dry-run          # count only
python3 tools/migrate_mysql_to_sqlite.py --report out.txt   # write
python3 tools/migrate_mysql_to_sqlite.py --users stress,foo
```

## Scope: only the named accounts

The legacy `caonima.account` table holds **6,388** registrations from the
original 2014 web site. They are obsolete and are **not** migrated: the tool
filters every table to the accounts named by `--users` (default `stress`). Every
query is scoped, including the `role_stage` / `role_account` lookups, which are
restricted to the selected accounts' role ids rather than read whole.

The whole in-scope data set is four rows: one account, one role, one stage row,
one currency row.

## Column mapping

| Legacy (MySQL) | Local (SQLite) | Notes |
| --- | --- | --- |
| `caonima.account.name` | `accounts.username` | Exact string, no prefixing. |
| `caonima.account.password` | `accounts.pass_hash` | Legacy **plaintext** → PBKDF2-SHA256 (100k iters). `char(32)` is only column *width*; the values are 4–8 printable chars. No plaintext is written to SQLite. |
| `dntg.user_role.id` | `characters.legacy_id` | Java role id, e.g. `fu0UR1-10-0-1`. Preserved so protocol replies and cross-table joins keep working. |
| `user_role.user_id` | `characters.account` | |
| `user_role.name` | `characters.name` | Migrated names carry the legacy ASCII prefix (e.g. `Tuan565.酆芷○訪蕊`). |
| `user_role.job` / `sex` / `face` | `characters.job` / `sex` / `face` | `job`/`face` are single letters. |
| `user_role.level` / `exp` | `characters.level` / `exp` | |
| `user_role.server_id` | `characters.server_id` | `fu1304`. |
| `role_stage.*` | `role_stage.*` | Same names as Java (see below). |
| `role_account.tongqian` / `bind_lingshi` | `characters.tongqian` / `bind_lingshi` | The only two currency columns the legacy table has. |
| `role_equip_slot` (goods/rare/blob) | `role_equip` | Slot rows for the gear attribute bag. |
| `role_attribute_buff` (attribute_id/count) | `role_attr_buff` | Shuxingdan pill rows for the dan bag. |
| `role_vip` (level/day/week/tejia/props) | `role_vip` | VIP level drives the buff push and the effect slots. |
| `role_xianjiechenhao` (`xianjie_id`/`chenhao_id` JSON) | `role_xianjiechenhao` | Xianjie id array + chenghao id array for the title bags. |
| `role_meiren` (meiren_id/level/heti) | `role_meiren` | One row per owned meiren; empty for the captured roles. |
| `role_zuoqi` (rank/cur_rank) | `role_zuoqi` | Mount rank gates the ZUOQI bag; `attribute_goods_id` is NULL for every role so it is not copied. |
| `role_bag_slot` (slot/goods/count/blob) | `role_bag_slot` | Bag slots 1..150 (151+ are storage); drives the 30000 goods maps. |
| `role_skillbook_slot` (slot/goods/count/blob) | `role_skillbook_slot` | Worn skillbook slots 10001..10056; drives the 99000 maps. |
| `role_bag_state` (capacities/timers) | `role_bag_state` | Capacities gate the 30000 lock VOs; timers feed the unlock countdown. |

`role_stage` is a **separate table** mirroring Java's `role_stage` columns, not extra
columns on `characters`. The SQLite table has 21 columns including `role_id`. The
migration copies 18 of the 20 non-key columns; `pk_info` and
`fly_count_refresh_time` are not in the migration's column list and keep their
defaults. `db.Store.list_roles` joins it and lets the stage row
win (`COALESCE(s.col, c.col)`), so `10003` (enter world) and `20000` (apply
stage) report the real map, coordinates and HP/MP instead of defaults.

## Traps found (both were live bugs, both now tested)

1. **Charset.** The bundled client is MySQL 5.1.37 and connects as `latin1` by
   default. Every CJK character in a `utf8` column came back as `?` —
   `Tuan565.酆芷○訪蕊` was migrated as `Tuan565.?????`. The client is now run
   with `--default-character-set=utf8` and stdout is decoded as UTF-8.
   (`utf8mb4` is *not* a compiled charset in 5.1; requesting it fails the
   connection outright.)
2. **NULL.** With `-N -B`, the client prints a SQL NULL as the literal text
   `NULL`, not `\N`. The first run therefore stored the four-character string
   `'NULL'` in `role_stage.buff`, `props`, `map_node`, `meiren_info`,
   `zuoqi_info` and `copy_info`. Those now map back to real `None`.

Both are covered by [tools/tests/test_migrate_mysql_to_sqlite.py](../tools/tests/test_migrate_mysql_to_sqlite.py)
without needing a live MySQL.

## Behaviour

- **Read-only on MySQL.** Credentials come from the ESSamp `config.inc.php` and
  are passed via `MYSQL_PWD`, never argv.
- **Backs up first.** The target DB is copied to `mko.db.pre-migration-<stamp>`
  before any write; restore by copying it back.
- **Repeatable.** Existing accounts and roles are left alone (`accounts_skipped`
  / `roles_skipped`), while `role_stage` and currency are re-applied, so a
  re-run repairs a partial write without creating duplicates.

## Deliberately not migrated

- The other ~504 `dntg` tables (chat logs, mail, friends, guilds, …). Add them
  per-table when a module actually needs them.
- `lingshi` / `recive_yb`: `role_account` has no source column for them, so they
  stay at 0 rather than being invented.
- The 6,388 legacy web registrations.
- Web-site tables (`caonima` mostly) beyond `account`.

## Verification

- `Server-v1/tests/test_protocol.py::TestMigratedRoleStage` asserts a
  stage-only role drives `list_roles`, `10003` and `20000`/bootstrap, and that
  empty stage blobs stay `None`.
- `tools/tests/test_migrate_mysql_to_sqlite.py` covers UTF-8 decoding, the NULL
  sentinel and account scoping.
- Live check against the running server: web login → `gamesession.php` → game
  socket `10001` → `10003` returned `['2', 10, 150]` with level 7 / exp 1310.

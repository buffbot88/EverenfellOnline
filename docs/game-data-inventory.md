# Legacy game data inventory

What the Java server reads, what our Python code can already decode, and what
still blocks a port of the game-data layer. Numbers come from
[tools/game_data_survey.py](../tools/game_data_survey.py), which tries every
table as raw AMF3 and as zlib-wrapped AMF3 and records where each one stops.

Status (re-run 2026-10-09 against the current codec, not written to `output/`):
496 of 728 files decode. The older report `output/game-data-survey3.json`
(128 of 728) no longer matches the current survey and is kept only as a snapshot.

## How the server loads its tables

Read from `dntg_start.jar` bytecode, not guessed:

- `com.xianling.configure.utils.ConfigParserUtil.getResource(byte[])` wraps the
  bytes in a `ByteArrayInputStream`, feeds them to **`flex.messaging.io.amf.Amf3Input`**
  (BlazeDS) and calls `readObject()`, cast to `Object[]`.
  So a `.jat` table is **standard AMF3**: one dense array whose elements are maps.
- Each config service names its own file. `MapLineConfigExportServiceImpl` stores
  the literal `MapLine.jat` and parses rows in `configureDataResolve` by map key
  (`mapid`, `mapname`, `maxlinevalue`, `tacitmaxpeople`, `rotateincrement`, ...).
  Those keys are exactly the CSV columns in `MapLine-back.csv`.
- `ClasspathConfigureLoader` loads from `config/game/sys_config/` and
  `config/game/map_config/`; `MapExportServiceImpl` mentions `path.mm`.

**Consequence:** the server reads **`.jat`** (and `.mm`) files, not `.dat`. The
`.dat` files carry client-side class names (`com.youbt.game.tbg.vo.MapInfo`), and
no jar in the legacy tree contains any `com/youbt` class, so those are not the
server's format.

## Census

| Extension | Files | Notes |
| --- | --- | --- |
| `.dat` | 307 | Client-side model classes; 191 decode, the 116 `map_config/*/map.dat` do not |
| `.jat` | 218 | **The server's config format** (BlazeDS AMF3); all 218 decode |
| `.mm` | 203 | 116 `path.mm` do not decode; 87 others (including `monster.mm`) decode |
| `.xml`/`.properties` | 60 | Spring, IBATIS, localisation, easyexecutor command wiring |
| **binary total** | **728** | 70 MB under `config/` |

## Decode status

**496 of 728 decode completely; 232 do not.** All 232 failures are two families:

| Count | File | Cause |
| --- | --- | --- |
| 116 | `map_config/*/map.dat` | `externalizable objects unsupported` — AMF3 feature not implemented |
| 116 | `map_config/*/path.mm` | `unsupported marker` at byte 3–4 — not AMF3 framing as we read it |

### What decodes and is directly useful

- `sys_config/MapLine.jat` decodes (91 rows). `config.load_map_lines` reads it
  for the per-map `maptype` used by command `21000`.
- `map_config/<id>/monster.mm` decodes for every map that has one, e.g.
  `map_config/107/monster.mm` (13 spawn groups) and the maps 2 and 5 that
  earlier notes listed as failing. `config.load_monsters` reads these to build
  the static `23002` snapshot. That is exactly the content command `23002` carries.

## Key blockers

1. **`externalizable` objects (116 files, all `map_config/*/map.dat`).** AMF3
   externalizable objects write their own bytes with no length, so they cannot
   be skipped without knowing the class. The class names come from the client
   (`com.youbt.game.tbg.vo.EngineVO`, `Array2DByteArray`), and those classes are
   in no server jar. A tolerant read that stops at the first externalizable
   object still yields `name` and `format` (an earlier run, not re-verified, gave map 5 → `'五庄观密室'`, `format = 1`).
2. **`path.mm` (116 files).** Not AMF3 as we currently read it: the first
   file starts `00 00 00 48 00 00 00 cc` and the reader fails at byte 3 (`unsupported marker 0x48`) in `map_config/0/path.mm`. The
   format is unidentified. No server code reads these yet.

## Hypotheses already tested and rejected

Recorded so they are not retried:

- **`format` is not the map type.** Map `format` is 1 for almost every map.
  Correlating it with the CSV's `maptype` gives 11 agree / 27 disagree. Dead.
- **Member names are not bare `utf-8-vr` in these files.** Changing the reader to
  treat class and member names as non-referencing `utf-8-vr` (excluding them from
  the string table) made things far worse: decodable files fell from 128 to 15 and
  6 protocol tests failed. BlazeDS keeps member names in the string table; the
  change was reverted. (Recorded against the codec at that time.)

## Recommended order of work

1. Identify the `path.mm` format (116 files, not AMF3 as read today). Check the
   jar for the reader class that consumes `path.mm` before guessing.
2. Treat the externalizable `map.dat` classes as a separate reverse-engineering
   effort; the client classes that define them are not in any server jar.
3. Keep `MapLine.jat` and `monster.mm` in the regression path: re-run the
   survey after any codec change and compare `summary.by_status`.

## Verification

- `python3 tools/game_data_survey.py` writes `output/game-data-survey.json`;
  re-run and compare `summary.by_status` after any codec change.
- `Server-v1` tests: 63 pass. `tools` tests: 25 pass.

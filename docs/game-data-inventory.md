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
| `.mm` | 203 | 116 `path.mm` do not decode as AMF3 (custom grid read by `load_path_grid`); 87 others (including `monster.mm`) decode |
| `.xml`/`.properties` | 60 | Spring, IBATIS, localisation, easyexecutor command wiring |
| **binary total** | **728** | 70 MB under `config/` |

## Decode status

**496 of 728 decode completely; 232 do not.** All 232 failures are two families:

| Count | File | Cause |
| --- | --- | --- |
| 116 | `map_config/*/map.dat` | `externalizable objects unsupported` — AMF3 feature not implemented |
| 116 | `map_config/*/path.mm` | `unsupported marker` at byte 3–4 — expected, custom grid format not AMF3 (see Key blockers) |

### What decodes and is directly useful

- `sys_config/MapLine.jat` decodes (91 rows). `config.load_map_lines` reads it
  for the per-map `maptype` used by command `21000`.
- `map_config/<id>/monster.mm` decodes for every map that has one, e.g.
  `map_config/107/monster.mm` (13 spawn groups) and the maps 2 and 5 that
  earlier notes listed as failing. `config.load_monsters` reads these to build
  the static `23002` snapshot. That is exactly the content command `23002` carries.

## Key blockers

1. **`map.dat` is not a server blocker.** No server class reads it. The server's
   per-map inputs come from `sys_config/maplist.dat`, which names only `monster.mm`,
   `path.mm` and `item.dat` for each map (114 rows; `item.dat` is not on disk, and
   `collectPath` is set but never loaded). The `map.dat` externalizable object is a client
   class (`com.youbt.game.tbg.vo.EngineVO`), and the server jar contains no `com/youbt`
   class. Layout below.
2. **`path.mm` is read** (`Server-v1/game/config.py`, `load_path_grid`). The format is
   a big-endian `int32` width and height, then one byte per cell (row-major, read to EOF).
   Cells with `(value & 31) != 0` are walkable (`PathInfoConfig.addPathNode`). 42 of 116
   files carry trailing bytes past `width × height`, which Java keeps. The `preprocess()`
   step is not recovered.

## `map.dat` layout (client-side; not read by the server)

Checked on all 116 files (for example, `map_config/0/map.dat` is 3,339 bytes compressed and
32,500 decompressed). Read with `Server-v1/game/mapdat.py`, tested in
`Server-v1/tests/test_mapdat.py`. The client SWF route is blocked (below), so the
layout was recovered from the bytes and validated by exact parses, not from source:

- Bytes 0–1: a zlib stream (`78 DA`) in all 116 files. Decompress before AMF3 parsing.
- Top level: AMF3 object of class `com.youbt.game.tbg.vo.MapInfo`, sealed members
  `last_update, format, settings, name, gwidth, gheight, author, mapwidth, mapheight,
  data, modelClass, guid` (map 0: `last_update` null, `format` 1).
- `settings`: dynamic object `com.youbt.game.tbg.vo.MapSettings` (22 sealed members;
  map 0: `cgw` 0, `right` 0, `bgrh` 24, `bgrw` 17, `bgheight` 256, `ver` 1).
- `settings.pathArray`: `com.youbt.utils.Array2DByteArray`, sealed members `ba, h, w`.
- `settings.enginevo`: **externalizable** `com.youbt.game.tbg.vo.EngineVO`. It is the
  first externalizable object in all 116 files. Its payload (`readExternal`) is:
  `readUTF('EngineVO2')` + 7 big-endian int32 (`3, 60, 30, 0, 0, 1000, 600` in every
  file) + 1 flag byte (`01` in every file), then a body of AMF3 values (`readObject`,
  shared string/object/traits tables) plus U29-prefixed section strings (`0x13` +
  `'layerinfo'`, registered in the string table like any AMF3 string).
- The body holds the walk grid (ByteArray, length exactly `path_mm` width × height:
  map 0 gives 14,688 = 72 × 204), the layer name and dims (map 0: `'凌霄殿外'`, 72,
  204), and a dynamic object of indexed `tbg.EleEffect` entries (26 sealed members
  each). Effect `id` values equal their wrapper keys (`'0'`, `'1'`, …), which proves
  the string-table alignment including the `layerinfo` registration.
- After the body come 2 trailing strings (map 0: `'com.youbt.game.tbg.map.MapModel'`,
  `'0'`). No file has room for the 23 outer values the traits imply (14 remaining
  settings members + 9 MapInfo members): map 0 ends with 2 values where 23 are due,
  and file endings across the set cut mid-structure 93 different ways. The outer
  tails are missing or truncated in these assets, so `load_map_dat` returns the
  EngineVO body with `outer` None and `complete` False.

Not established: the meaning of `format`, the 7 header ints, and whether the
client uses this file for collision. Nothing in the server depends on it.

### Why not from the client SWFs

`EngineVO.readExternal` lives only in the client. The readable SWFs (`Main.swf`,
`PlatformLoader.swf`, `MPlayer.swf`, `lib.swf`) contain only `com.youbt.{asm,core,
events,manager,utils}` — no `vo` package and no `EngineVO` string. The SWF that
should define it (`tg.swf`, plus `mapPlugin.swf` et al.) is encrypted (see
[swf-encryption-notes.md](swf-encryption-notes.md): 193 files, still unsolved), and
`abc_strings.py` fails on it with “not a plain SWF”. So the layout above comes from
byte-level recovery validated across all 116 files, not from decompilation.

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

1. (Done) `path.mm` is read by `load_path_grid`; golden tests cover all 116 files.
2. `map.dat` is client-side. Only pursue it if the client's collision or rendering needs
   reverse-engineering, not for the server port.
3. Keep `MapLine.jat` and `monster.mm` in the regression path: re-run the
   survey after any codec change and compare `summary.by_status`.

## Verification

- `python3 tools/game_data_survey.py` writes `output/game-data-survey.json`;
  re-run and compare `summary.by_status` after any codec change.
- `Server-v1` tests: 101 pass. `tools` tests: 26 pass.

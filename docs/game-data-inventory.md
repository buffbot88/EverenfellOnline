# Legacy game data inventory

What the Java server reads, what our Python code can already decode, and what
still blocks a port of the game-data layer. All numbers come from
[tools/game_data_survey.py](../tools/game_data_survey.py), which tries every
table as raw AMF3 and as zlib-wrapped AMF3 and records where each one stops
(report: `output/game-data-survey3.json`).

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
| `.dat` | 307 | Client-side model classes; many also zlib-wrapped |
| `.jat` | 218 | **The server's config format** (BlazeDS AMF3) |
| `.mm` | 203 | Per-map spawn/path tables (`monster.mm`, `path.mm`) |
| `.xml`/`.properties` | 60 | Spring, IBATIS, localisation, easyexecutor command wiring |
| **binary total** | **728** | 70 MB under `config/` |

## Decode status

**128 of 728 decode completely; 600 do not.** By extension: 54 `.dat`, 47 `.jat`,
27 `.mm`.

Failure breakdown:

| Count | Cause |
| --- | --- |
| 419 | `unsupported marker 0xNN` — the decoder ran off the rails (desync), not necessarily a missing marker |
| 87 | `IndexError` — read past the end (desync or truncated) |
| 80 | `externalizable objects unsupported` — real AMF3 feature we do not implement |
| 12 | `UnicodeDecodeError` — treated bytes as UTF-8 where they are not |
| 1 | `struct` unpack |

The 600 failures cluster on the same few tables repeated across maps, so the
distinct-format count is far smaller than the file count.

### What decodes and is directly useful

`monster.mm` for 27 maps yields real spawn data, e.g. `map_config/107/monster.mm`
(97 values): `{'monsterType': 1, 'team': 0, 'maxCount': 999,
'createPoints': [[24, 111, 0], [23, 112, 0], ...]}` with monster names and ids
like `D140017`. That is exactly the content command `23002` carries.

**But not the maps we need:** `map_config/2/monster.mm` fails at 584 (marker
`0x30`) and `map_config/5/monster.mm` at 203 (marker `0x0f`).

## Key blockers

1. **`externalizable` objects (80 files, all `map_config/*/map.dat`).** AMF3
   externalizable objects write their own bytes with no length, so they cannot
   be skipped without knowing the class. The class names come from the client
   (`com.youbt.game.tbg.vo.EngineVO`, `Array2DByteArray`), and those classes are
   in no server jar.
2. **`MapLine.jat`** (the `mapType` source for command `21000`) fails at byte 303
   with marker `0x1e`. The same table's readable backup, `MapLine-back.csv`, is a
   Dec-2013 export with 42 rows and no entry for map 2.
3. **`path.mm`** starts with `0x00` at offset 0 — not AMF3 at all.
4. **`map_config/<id>/map.dat`** decodes only partially. A tolerant read that
   stops at the first externalizable object does yield `name` and `format`, e.g.
   map 5 → `'五庄观密室'`, `format = 1`.

## Hypotheses already tested and rejected

Recorded so they are not retried:

- **`format` is not the map type.** Map `format` is 1 for almost every map.
  Correlating it with the CSV's `maptype` gives 11 agree / 27 disagree. Dead.
- **Member names are not bare `utf-8-vr` in these files.** Changing the reader to
  treat class and member names as non-referencing `utf-8-vr` (excluding them from
  the string table) made things far worse: decodable files fell from 128 to 15 and
  6 protocol tests failed. BlazeDS keeps member names in the string table; the
  change was reverted.

## Recommended order of work

1. Get `MapLine.jat` decoding. It is one file, it is plain AMF3, and it unblocks
   the real per-map `mapType` for every map instead of a default guess.
2. Then `monster.mm` for the maps actually in use, to populate `23002` from real
   spawn points rather than inventing them.
3. Treat `path.mm` and the externalizable `map.dat` classes as a separate
   reverse-engineering effort; neither is AMF3 as we currently read it.

## Verification

- `python3 tools/game_data_survey.py` writes `output/game-data-survey.json`;
  re-run and compare `summary.by_status` after any codec change.
- `Server-v1` tests: 43 pass. `tools` tests: 25 pass.

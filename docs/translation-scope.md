# Translation scope (Chinese → English)

Goal: every player-visible string in the rebuilt game is English. This page
records where the Chinese text lives, measured on 2026-10-09, and the limits of
those measurements.

## Where the text is

| Source | Measured | Notes |
| --- | --- | --- |
| Client SWFs (`MKO_Client/Assets/**/*.swf`) | 199 files; 193 encrypted or non-standard | UI labels and dialogue are inside these files. They cannot be read until the encryption is solved. Strings are not counted. |
| Locale config (`MKO_Client/Assets/res/config/**`) | 16 locale branches (`tw`, `zhcn`, `kokr`, `us`, `thai`, `dama`, ...) | Per-locale XML and data. The default locale is `tw`. |
| Server config tables (`reference/TonNgoKhong/server/config/**`) | `.jat`, `.mm`, `.dat` binaries | Item, monster, and map names are AMF3 strings inside these files. |
| Legacy PHP and JS web pages (`reference/TonNgoKhong/server/ESSamp/wwwroot/**`) | see below | Login and game-session pages. |
| Java server (`dntg_start.jar`) | not measured | Any user-facing strings are compiled constants; not searched yet. |

## Measured counts

Text-like files that contain at least one CJK character (U+4E00–U+9FFF):

| Extension | Files with CJK | Total scanned |
| --- | ---: | ---: |
| `.xml` | 26 | 47 |
| `.js` | 20 | 43 |
| `.php` | 36 | 77 |
| `.txt` | 15 | 24 |
| `.html` | 7 | 7 |
| `.csv` | 2 | 4 |

Binary tables, counted by decoding raw bytes as UTF-8 (a rough heuristic, not
a real string extraction, so these are likely overcounts):

| Extension | Files with CJK | Total scanned |
| --- | ---: | ---: |
| `.dat` | 689 | 1,072 |
| `.mm` | 173 | 423 |
| `.jat` | 131 | 443 |

## Risks

- **Font rendering.** The Ruffle client logs `Unknown device font "SimSun"`,
  so device Chinese text cannot display there. Any English build needs its own
  font and no reliance on SimSun.
- **Encrypted SWFs hide the UI strings.** Until the SWFs are decoded or the UI is
  rebuilt, the full string set is unknown. Those strings are the largest unknown.
- **Mixed encodings.** The legacy MySQL client needs `--default-character-set=utf8`
  or CJK becomes `?` (see [mysql-to-sqlite-migration.md](mysql-to-sqlite-migration.md)).
- **Names carry a legacy prefix.** Migrated character names keep an ASCII
  prefix (`Tuan565.…`). Renaming or re-keying must not break role lookups.

## Next step

1. Extract all strings from the AMF3 tables and XML/PHP/JS files into one
   table, keyed by source file, and count them. The AMF3 decoder can already
   read the `.jat` tables.
2. Decide the translation workflow: machine draft with a glossary, then
   human review of game terms.
3. Plan the SWF string extraction once the encryption question is settled.

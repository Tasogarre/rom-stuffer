# feat: ROM de-duplication + package refactor + theme expansion (Phase 1)

**Created:** 2026-07-17
**Type:** feat
**Depth:** Deep
**Design of record:** [`docs/DESIGN.md`](../DESIGN.md)

## Summary

Add a hash-identical **de-duplication** capability to ROM Stuffer, refactor the
single `compress_roms.py` into a `rom_stuffer` package with subcommands, and expand
the themes (Kirby as new default, add Tetris, upgrade Metroid). Phase 1 also produces
a durable **hash index** in the shape phase 2's per-system space estimator needs.

## Problem frame

Users assembling SD cards for RetroArch handhelds want to fit the most games in the
space. Compression already helps; **byte-identical duplicate ROMs waste space** and
there is no way to find or remove them. The codebase is a single ~1,000-line file
that is at the natural point to split before adding a second capability.

## Scope boundaries

**In scope (phase 1):** package refactor + entry rename; `compress`/`dedup`
subcommands + no-arg menu; logical-content hashing (raw + zip); duplicate detection;
keeper rules + knobs; TUI plan review/edit/apply; quarantine/delete executor; dedup
reporting; persisted hash index; Kirby/Tetris/Metroid themes.

### Deferred to follow-up work (phase 2+)

- Per-system space estimator (compressed vs decompressed) + selective SD sync.
- Fuzzy / DAT / name-based dedup of *variants* (phase 1 is byte-identical only).

### Out of this product's identity

- Converting raw ↔ zip during dedup; any change to the disc/BIOS exclusion policy.

## Key technical decisions

- **KTD1 — Container-agnostic logical hashing.** Bucket by *uncompressed* size, use
  zip central-directory CRC-32 as a free pre-filter, confirm with SHA-256 by
  streaming zip entries in memory. Never mass-unzip. (Design §4.2.)
- **KTD2 — Behaviour-preserving refactor.** Move code into `rom_stuffer/` modules
  without changing `compress` behaviour; keep `compress_roms.py` as a shim.
- **KTD3 — Plan → review → apply, TUI-primary.** A persisted dedup plan + hash index;
  reviewed/edited inside the TUI; `--interactive` per-group only for small runs.
- **KTD4 — Reversible by default.** Quarantine (move) is the default removal mode;
  hard-delete is a runtime opt-in. Dedup defaults to preview.
- **KTD5 — Reuse guards.** Dedup enumerates via the same scan + `exclusion_reason`,
  so BIOS/disc files are never hashed, moved, or deleted.

## Output structure

See Design §3.1 for the target `rom_stuffer/` package tree.

---

## Phase 1a — Package refactor (behaviour-preserving)

### U1. Extract `rom_stuffer` package from `compress_roms.py`

- **Goal:** split the single file into the module layout (Design §3.1) with no
  behaviour change to `compress`.
- **Dependencies:** none.
- **Files:** create `rom_stuffer/__init__.py`, `__main__.py`, `tui.py`, `themes.py`,
  `guards.py`, `scan.py`, `metrics.py`, `report.py`, `state.py`, `compress.py`;
  create `rom_stuffer.py` (entry) and convert `compress_roms.py` to a shim; move the
  existing helpers into their modules; add `tests/test_refactor_smoke.py`.
- **Approach:** mechanical move + re-export. `guards.py` holds
  `SUPPORTED_EXTENSIONS`, `DISC_SYSTEM_FOLDERS`, `exclusion_reason`, `describe_error`;
  `tui.py`/`themes.py` hold the console, palette registry, `print_header`, prompts;
  `compress.py` holds `build_zip_path`, `compress_batch`, `fast_sd_copy`. Keep public
  function names stable to minimise churn.
- **Execution note:** characterise first — run the existing manual test flows
  (collision, resume, `.bin` guard) before and after to prove behaviour is identical.
- **Test scenarios:** import smoke (`import rom_stuffer`, `python -m rom_stuffer`
  works); the collision case still yields `Game.zip` + `Game_gb.zip`; resume after a
  simulated crash still completes; `.bin` under `psp/` still refused, `megadrive/`
  kept; `compress_roms.py` prints a deprecation notice and still runs.
- **Verification:** all pre-refactor manual flows pass unchanged; no behaviour diff.

### U2. CLI subcommands + no-arg interactive menu

- **Goal:** `compress` and `dedup` subcommands; no-arg launch shows the menu
  (Compress / Find duplicates / Both).
- **Dependencies:** U1.
- **Files:** `rom_stuffer/cli.py`; `tests/test_cli.py`.
- **Approach:** argparse subparsers over a shared parent parser (source/dest/sdcard/
  dry-run/theme/resume). No-arg → themed menu via the existing prompt style. `dedup`
  wiring is stubbed until Phase 1b/1c land; `Both` sequences dedup→compress.
- **Test scenarios:** `compress -s -d` routes to the compress flow; `dedup -s -d`
  routes to the dedup entry; no args → menu; menu selection 1/2/3 routes correctly;
  `--help` lists subcommands; unknown subcommand errors cleanly.
- **Verification:** each route reaches the right handler; existing compress
  invocation still works (via `compress` subcommand and the shim).

---

## Phase 1b — De-duplication engine

### U3. Logical-content hashing

- **Goal:** hash a ROM's logical content whether raw or zipped, cheaply.
- **Dependencies:** U1.
- **Files:** `rom_stuffer/hashing.py`; `tests/test_hashing.py`.
- **Approach:** `logical_size(path)` — `stat` for raw, sum of entry `file_size` for
  zips (from `ZipInfo`, no decompression). `quick_fingerprint(path)` — zip CRC-32
  from metadata; raw partial hash (first+last 64 KB). `content_sha256(path)` — raw
  file streamed; zip entries streamed via `ZipFile.open()` and hashed in memory
  (constant peak memory), never extracted. (Design §4.2.)
- **Test scenarios:** raw and a one-entry zip of the *same* bytes produce the *same*
  `content_sha256`; different content → different hash; `logical_size` matches for
  raw vs zip of same content; zip hashing never writes to disk (assert no temp
  files); large-file hashing stays within a memory bound (streamed); corrupt/
  unreadable file → handled error, not crash.
- **Verification:** identical raw vs zipped ROMs hash equal; memory stays bounded.

### U4. Duplicate detection pipeline

- **Goal:** produce duplicate groups from a source tree, reusing scan + guards.
- **Dependencies:** U1, U3.
- **Files:** `rom_stuffer/dedup.py`; `tests/test_dedup_detect.py`.
- **Approach:** enumerate ROM candidates via `scan` + `exclusion_reason` (BIOS/disc
  skipped); bucket by `logical_size`; drop singleton buckets; within multi-member
  buckets apply `quick_fingerprint`; confirm survivors with `content_sha256`; group
  by hash. Emit `(hash → [paths])` sets of size ≥ 2. (Design §4.2.)
- **Test scenarios:** two identical-content files (raw+raw, raw+zip, zip+zip) group
  together; different-size files never read (assert stat-only for singletons); a
  three-way duplicate set groups all three; BIOS/disc files never appear in any
  group; a unique library yields zero groups.
- **Verification:** correct groups on a mixed raw/zip fixture; singletons never
  content-hashed.

### U5. Keeper rules + global knobs

- **Goal:** choose which copy to keep per duplicate set, tunably.
- **Dependencies:** U4.
- **Files:** `rom_stuffer/dedup.py` (keeper functions); `tests/test_keeper.py`.
- **Approach:** default heuristic (Design §4.4): de-prioritise junk folders / `(1)`/
  `copy` names; prefer clean No-Intro names; prefer compressed copy; prefer shallow
  path; deterministic alphabetical tie-break. Knobs: `--keeper-order` (folder
  priority), `--protect` (never removed / preferred), `--per-system`, `--min-size`.
- **Test scenarios:** default picks the compressed copy over raw when content equal;
  `--keeper-order` overrides to the priority folder; `--protect` folder is always
  kept and never removed; `--per-system` prevents cross-system grouping;
  `--min-size` excludes tiny sets; tie-break is deterministic across runs.
- **Verification:** keeper choice is deterministic and honours every knob.

### U6. Dedup plan + hash index persistence

- **Goal:** a persisted, human-editable plan + the phase-2 hash index.
- **Dependencies:** U4, U5.
- **Files:** `rom_stuffer/planfile.py`; `tests/test_planfile.py`.
- **Approach:** plan model = list of groups, each with keeper + removals + reclaimed
  bytes; save/load a human-readable plan file (keeper marked, removals listed;
  editable, groups skippable). Hash index = per-ROM `{path, sha256, logical_size,
  stored_size}` written to `<dest>/.rom_stuffer_hash_index.json` (Design §4.3).
  Reuse `state.py` atomic-write patterns.
- **Test scenarios:** round-trip save/load preserves groups + keeper choices; a
  hand-edited keeper is honoured on load; a commented-out group is skipped; hash
  index contains logical + stored sizes for raw and zip; corrupt plan file → clean
  error, no destructive action.
- **Verification:** edited plan applies exactly as edited; index has both sizes.

---

## Phase 1c — De-duplication TUI + execution

### U7. TUI plan review / edit / apply

- **Goal:** review, adjust keepers, skip groups, and confirm — inside the TUI.
- **Dependencies:** U6.
- **Files:** `rom_stuffer/review.py`; `tests/test_review.py`.
- **Approach:** Rich-based paginated review of duplicate groups (themed): show each
  group's keeper + removals + reclaimed space; accept-all, change keeper by number,
  skip a group, then apply. `--interactive` per-group only; default is the summary +
  confirm. (Full-screen Textual UI noted as a future upgrade, not phase 1.)
- **Test scenarios:** summary shows group count + total reclaimable; changing a
  keeper updates the plan; skipping a group excludes it from apply; `accept-all`
  applies the computed plan; pagination handles many groups; markup-escaped
  filenames (bracket tags) render without crashing.
- **Verification:** the applied plan matches what was shown/edited in the TUI.

### U8. Dedup executor (quarantine / delete)

- **Goal:** apply an approved plan safely, reversibly by default.
- **Dependencies:** U6, U7.
- **Files:** `rom_stuffer/dedup.py` (executor); `tests/test_dedup_apply.py`.
- **Approach:** for each removal, quarantine (move to `<dest>/dedup_backup/` preserving
  relative path) by default; hard-delete only on runtime opt-in. Reuse the move +
  resume/journal patterns; dry-run touches nothing. Never act on a keeper. Update
  metrics (files removed, space reclaimed).
- **Test scenarios:** quarantine moves removals and leaves keepers in place; structure
  preserved in the backup; dry-run changes nothing but reports totals; hard-delete
  removes only removals (never keepers); interrupted apply resumes without
  double-processing; failure on one file is recorded and does not abort the batch.
- **Verification:** only redundant copies are removed; keepers untouched; reversible.

### U9. Dedup reporting

- **Goal:** report duplicate groups, reclaimed space, keeper→removed mapping.
- **Dependencies:** U8.
- **Files:** `rom_stuffer/report.py` (dedup report); `tests/test_dedup_report.py`.
- **Approach:** extend `generate_reports` (or a sibling) with a dedup summary panel
  (groups found, files removed, space reclaimed) + a keeper→removed table, console +
  `rom_stuffer_report.txt`, themed, dry-run labelled. Reuse the live space readout
  idea for the hashing pass ("hashed X / Y").
- **Test scenarios:** report lists each group's keeper + removals; totals match the
  plan; dry-run is labelled estimated; clean single-backslash paths on Windows
  (reuse `describe_error`); console table caps large runs.
- **Verification:** report totals reconcile with the executor's actions.

### U10. "Both" flow (dedup → compress)

- **Goal:** one command / menu choice that de-dupes then compresses the survivors.
- **Dependencies:** U2, U8, compress.
- **Files:** `rom_stuffer/cli.py`; `tests/test_both_flow.py`.
- **Approach:** run dedup to completion (plan → apply), then feed the remaining files
  into the existing compress flow. Shared session metrics/report so the user sees
  combined space saved (dedup + compression).
- **Test scenarios:** duplicates removed before compression; survivors compressed;
  combined report shows both dedup and compression savings; dry-run previews both
  stages without changes.
- **Verification:** end-to-end on a mixed fixture: duplicates gone, survivors zipped,
  totals correct.

---

## Phase 1d — Themes

### U11. Kirby default + Tetris theme + Metroid emblem upgrade

- **Goal:** Kirby becomes the default/primary theme; add Tetris; upgrade Metroid.
- **Dependencies:** U1.
- **Files:** `rom_stuffer/themes.py`; `assets/banner.*` (Kirby-primary),
  `assets/screenshot-*.png`; `README.md`; `tests/test_themes.py`.
- **Approach:** add `kirby` (pink palette, original puffball emblem) and set it as
  `DEFAULT_THEME`; add `tetris` (tetromino palette + stacked-blocks emblem); upgrade
  the Metroid emblem. **All emblems are original homage pixel-art** (no third-party/
  character artwork committed — Design §5). Regenerate the README banner + theme
  screenshots.
- **Test scenarios:** `--theme kirby|tetris|zelda|metroid` each apply; default is
  `kirby`; unknown theme falls back to default; every semantic style resolves for
  each theme; emblems centre symmetrically (per the fixed centring rule).
- **Test expectation:** emblem art is visually reviewed via rendered screenshots.
- **Verification:** all four themes render correctly; Kirby is the default.

---

## Verification contract

- Behaviour-preserving refactor proven by the pre-existing manual flows (U1).
- Dedup correctness on a mixed raw/zip fixture with duplicates, uniques, BIOS, and
  disc files (U4, U8).
- Reversibility: quarantine restores the original layout (U8).
- Combined "Both" flow end-to-end (U10).
- Themes render + default is Kirby (U11).

## Definition of done

Every unit's tests pass; `compress` behaviour is unchanged; `dedup` finds and safely
removes byte-identical duplicates (quarantine default) with a TUI-reviewable plan;
the hash index is persisted with logical + stored sizes; Kirby is the default theme;
README updated. No change to the disc/BIOS exclusion policy.

## Open questions (defer to implementation)

- Exact plan-file format (TSV vs simple annotated text) — decide when building U6;
  requirement is human-editable + skippable groups.
- Whether `state.py` resume should span the hashing pass or only the apply pass —
  decide from real timing on a large set.

# ROM Stuffer Phase 1 — Detailed Build Plan

**Expands:** `docs/plans/2026-07-17-001-feat-dedup-and-package-refactor-plan.md`
**Design of record:** `docs/DESIGN.md`
**Created:** 2026-07-17

---

## How to Use This Plan

You are a building agent executing this plan unit-by-unit. Read the following rules before
touching any file.

**What this plan gives you.** For every implementation unit (U1-U11) you will find:
exact target file paths, function/class signatures with full type annotations, a
docstring-level contract (preconditions, postconditions, error behaviour), algorithm
pseudocode numbered step-by-step, concrete data schema examples, specific test
scenarios with named fixtures and exact expected outputs, and inter-unit dependencies.

**What you must NOT do.** Do not write function bodies from memory. Use the pseudocode
in this document. Do not invent data formats. Use the schemas in Appendices A, B, C
exactly. Do not add extensions to `SUPPORTED_EXTENSIONS`. Do not touch the disc/BIOS
guard logic beyond moving it. Do not reorder the keeper heuristic rules.

**Execution order.** Follow the wave table in the next section. Within a wave, units
are file-disjoint and may be executed concurrently. Never start a unit until all its
declared dependencies are done and their tests pass.

**Verification.** Each unit defines its own verification steps. The minimum bar before
marking a unit done: all unit tests listed under that unit pass; no previously passing
test regresses; the specific invariants stated in "Safety Invariants" below are intact.

**Import paths.** During U1 (refactor) use `import compress_roms`. After U1, tests use
`import rom_stuffer` and submodule imports like `from rom_stuffer.hashing import
content_sha256`. The shim at `compress_roms.py` must keep the old import path working
throughout.

**Test infrastructure (AUTHORITATIVE — already built and shipped).** The test
foundation exists on `main`: `pyproject.toml` (pytest config; `pythonpath=[".","tests"]`),
`conftest.py` (autouse fixture clearing `guards._disc_dir_cache` between tests),
`tests/helpers.py`, and `tests/crash_sim.py`. **Wherever a later section of this plan
names `make_rom_tree(...)` or `CrashSimulator`, use the real API below instead** — the
concepts map one-to-one:

- `tests/helpers.py` provides a **fluent `RomTree` builder** (not a dict-spec function):
  `RomTree(tmp_path)` with chainable methods `.cartridge(system, name, content=..., size=...)`,
  `.cartridges(...)`, `.disc_folder(system, name, descriptor=".cue"|".gdi")`,
  `.bios(name)`, `.oversized_bin(...)`, `.duplicate_pair(...)` (same content, different
  names/folders), `.zip_pair(...)` (a raw file + a `.zip` of the same content),
  `.unicode_rom(...)`, `.bracket_rom(...)`. Plus module functions `make_zip(dest, rom_name,
  content)` and `rom_bytes(size=64, seed=...)`, and two pytest fixtures. Build the tree you
  need per test with these methods rather than a path→bytes dict.
- `tests/crash_sim.py` provides **`CrashAfterN`** (context manager, `fail_at` count,
  raises KeyboardInterrupt for a hard crash) and **`install_crashing_move(monkeypatch,
  n, exc=OSError)`** — both patch `shutil.move` globally (resolved at call time). Use these
  for resume/failure tests; call `monkeypatch.undo()` before a follow-up resume run.

All test modules `import compress_roms as rs` (the compat shim). 84 behaviour tests
already cover the current features (collision, resume, .bin/disc/BIOS guards, path
guards, `describe_error`); new dedup tests join them under `tests/`.

**Repo-relative paths only.** Every path in this document is relative to the repo
root. "worktree root" and "repo root" are the same directory.

---

## Execution Waves

| Wave | Units | Parallelisable | Dependencies |
|------|-------|---------------|-------------|
| 0 | U1 | no | none |
| 1 | U2, U3, U11 | yes (file-disjoint) | U1 |
| 2 | U4 | no | U1, U3 |
| 3 | U5, U6 | yes (file-disjoint) | U4 (U5); U4, U5 (U6) |
| 4 | U7, U8 | yes (file-disjoint) | U6 |
| 5 | U9, U10 | yes (U9: report.py; U10: cli.py) | U8 |

---

## Global Safety Invariants

These invariants must hold after every unit and are tested across multiple units.

1. **BIOS/disc guard untouched.** `exclusion_reason` is moved (U1) but never modified.
   Any path under a `bios` folder or beside a `.cue`/`.gdi` descriptor must be refused
   by every enumeration: compress scan, dedup scan, both flow.

2. **Quarantine is reversible.** The dedup executor's default (quarantine) moves files
   to `<dest>/dedup_backup/<relative_path>` preserving structure. Moving them back
   restores the original layout exactly.

3. **Dedup defaults to preview.** Calling the dedup entry with no `--apply` flag must
   NOT move or delete any files. The plan is printed and saved; the user must explicitly
   confirm (TUI) or pass `--apply-plan` to act.

4. **Compress behaviour unchanged.** The `compress` subcommand (and the shim) must
   produce byte-identical results to `compress_roms.py` before the refactor, for the
   same inputs. The existing test flows — collision disambiguation, resume-after-crash,
   `.bin` guard — must all still pass after U1.

5. **Emblem symmetry.** Every theme emblem in `themes.py` must use only symmetric
   markup: no leading or trailing whitespace in any emblem row; Rich centring must
   produce visually centred art. The existing rule from `print_header()` —
   "each emblem row holds only symmetric content" — applies to all new emblems.

6. **describe_error for Windows paths.** Any error path displayed to the user must go
   through `describe_error(e)` to avoid doubled backslashes on Windows.

7. **No extension additions.** `SUPPORTED_EXTENSIONS` in `guards.py` must be identical
   to the set in `compress_roms.py` after the refactor. Dedup does not add extensions.

---

## U1: Extract `rom_stuffer` Package

**Dependencies:** none.
**Execution wave:** 0.
**Files created:**
```
rom_stuffer/__init__.py
rom_stuffer/__main__.py
rom_stuffer/themes.py
rom_stuffer/tui.py
rom_stuffer/guards.py
rom_stuffer/scan.py
rom_stuffer/metrics.py
rom_stuffer/report.py
rom_stuffer/state.py
rom_stuffer/compress.py
rom_stuffer/cli.py          # stub only; U2 fills it out
rom_stuffer.py              # new top-level entry point
compress_roms.py            # converted to deprecation shim (edit in place)
tests/__init__.py           # empty, enable package imports
tests/helpers.py            # test infrastructure (see contracts below)
tests/test_refactor_smoke.py
```
**Files NOT created in this unit:** `hashing.py`, `dedup.py`, `planfile.py`,
`review.py` — those belong to later units.

### Module Assignments

| Symbol | Source location | Target module |
|--------|----------------|---------------|
| `THEMES`, `DEFAULT_THEME`, `ZELDA_ART`, `METROID_ART`, `apply_theme` | compress_roms.py | `rom_stuffer/themes.py` |
| `console`, `_active_theme`, `print_header`, `print_warning_banner`, `section` | compress_roms.py | `rom_stuffer/tui.py` |
| `SUPPORTED_EXTENSIONS`, `CARTRIDGE_BIN_MAX_BYTES`, `DISC_DESCRIPTOR_SUFFIXES`, `DISC_SYSTEM_FOLDERS`, `_disc_dir_cache`, `_dir_has_disc_descriptor`, `exclusion_reason`, `describe_error` | compress_roms.py | `rom_stuffer/guards.py` |
| `SessionMetrics`, `format_size` | compress_roms.py | `rom_stuffer/metrics.py` |
| `generate_reports` | compress_roms.py | `rom_stuffer/report.py` |
| `STATE_VERSION`, `STATE_FILENAME`, `JOURNAL_FILENAME`, `JOURNAL_FSYNC_INTERVAL`, `_state_paths`, `load_manifest`, `read_journal`, `write_manifest`, `clear_state`, `ResumeState` | compress_roms.py | `rom_stuffer/state.py` |
| `FAST_COPY_BUFFER_BYTES`, `SCAN_FOLDER_SAMPLE`, `CONSOLE_TABLE_ROW_CAP`, `DRY_RUN_COMPRESSION_ESTIMATE`, `fast_sd_copy`, `build_zip_path`, `compress_batch`, `_build_worklist_interactive`, `compress_roms`, `_finalise_session` | compress_roms.py | `rom_stuffer/compress.py` |
| `_build_parser` (argparse), `main` (CLI entry) | compress_roms.py `__main__` block | `rom_stuffer/cli.py` (stub) |

### Function Signatures and Contracts

#### `rom_stuffer/__init__.py`
```python
"""
rom_stuffer package — public API surface.

Re-exports the primary callable and data classes so callers can do:
    from rom_stuffer import compress_roms, SessionMetrics
"""
from rom_stuffer.compress import compress_roms
from rom_stuffer.metrics import SessionMetrics, format_size
from rom_stuffer.guards import exclusion_reason, describe_error

__version__: str = "2.0.0"
__all__ = ["compress_roms", "SessionMetrics", "format_size",
           "exclusion_reason", "describe_error", "__version__"]
```

#### `rom_stuffer/__main__.py`
```python
"""Enables `python -m rom_stuffer`."""
from rom_stuffer.cli import main
if __name__ == "__main__":
    main()
```

#### `rom_stuffer/themes.py` — signature contracts

```python
THEMES: dict[str, dict]
# Schema: {name: {"styles": {semantic: rich_style_str}, "art": str,
#                 "label": str, "tagline": str, "border": str}}
# Semantic keys required: brand, accent, info, success, warn, danger, muted, value, path.
# Precondition on art: every line is symmetric (no leading/trailing whitespace outside markup).

DEFAULT_THEME: str  # = "zelda" until U11 changes it to "kirby"

def apply_theme(name: str) -> None:
    """Activate a named theme.
    Precondition: name is in THEMES or will be normalised to DEFAULT_THEME.
    Postcondition: console has the theme's palette pushed; _active_theme["name"] updated.
    Error: unknown name silently falls back to DEFAULT_THEME (never raises)."""
```

#### `rom_stuffer/guards.py` — signature contracts

```python
def exclusion_reason(
    path: Path,
    ext: str,
    size: int | None,
    source: Path | None = None,
) -> str | None:
    """Return a human-readable reason to refuse a file, or None if safe.
    Preconditions:
      - path exists (caller verifies); ext is path.suffix.lower().
      - source, if given, is the root of the scan tree.
    Postconditions:
      - Returns None iff the file is a genuine cartridge ROM safe to process.
      - Returns a non-empty string for BIOS folders (any ext), .bin disc images, etc.
      - Only folder names INSIDE the source tree are consulted.
    Error: OSError from iterdir is caught and returns False for _dir_has_disc_descriptor."""

def describe_error(e: Exception) -> str:
    """Return a clean, single-backslash error string.
    Preconditions: e is any Exception.
    Postconditions: OSError with strerror → 'strerror: filename' (raw filename, no repr).
                    Other exceptions → str(e).
    Error: never raises."""
```

#### `rom_stuffer/metrics.py` — signature contracts

```python
class SessionMetrics:
    """Accumulates compress-pass statistics across all batches in a session.
    All numeric fields initialise to 0; lists to []; dry_run to False.
    Mutated in place by compress_batch; read by generate_reports."""
    total_files: int
    original_size_bytes: int
    zip_size_bytes: int
    success_count: int
    error_count: int
    sd_files_synced: int
    sd_bytes_copied: int
    affected_folders: set
    errors: list       # [{"file": str, "error": str}]
    skipped_files: list  # [{"file": str, "reason": str}]
    dry_run: bool

def format_size(size_bytes: int) -> str:
    """Human-readable size: B / KB / MB / GB.
    Precondition: size_bytes >= 0.
    Postcondition: returns a string with a unit suffix, 2 decimal places for KB+.
    Error: never raises."""
```

#### `rom_stuffer/state.py` — key signatures (unchanged from compress_roms.py)

```python
STATE_VERSION: int = 1
STATE_FILENAME: str = ".rom_stuffer_state.json"
JOURNAL_FILENAME: str = ".rom_stuffer_journal.log"
JOURNAL_FSYNC_INTERVAL: int = 200

def load_manifest(dest_path: Path) -> dict | None: ...
def read_journal(dest_path: Path) -> set[str]: ...
def write_manifest(dest_path: Path, source_path: Path, pending_rel: list[str]) -> None: ...
def clear_state(dest_path: Path) -> None: ...

class ResumeState:
    def __init__(self, dest_path: Path, done: set[str]) -> None: ...
    def is_done(self, rel: str) -> bool: ...
    def mark_done(self, rel: str) -> None: ...
    def close(self) -> None: ...
```

#### `rom_stuffer/cli.py` (U1 stub — U2 fills it out)

```python
def main() -> None:
    """Entry point. In U1 stub: re-parse args and call compress_roms with the same
    argparse logic that was in compress_roms.py __main__. U2 will replace with
    subcommand routing."""
```

#### `rom_stuffer.py` (top-level entry)

```python
"""New primary entry point. Delegates to rom_stuffer.cli:main."""
from rom_stuffer.cli import main
if __name__ == "__main__":
    main()
```

#### `compress_roms.py` (shim — edit in place)

```python
"""
compress_roms.py — deprecation shim.

This file is kept for backward compatibility. The application has moved to
rom_stuffer.py. All behaviour is preserved; this shim simply notifies and forwards.
"""
import sys
print(
    "Notice: compress_roms.py is a compatibility shim. "
    "Use 'python rom_stuffer.py' going forward.",
    file=sys.stderr,
)
from rom_stuffer.cli import main
if __name__ == "__main__":
    main()
```

### `tests/helpers.py` — API Contract

```python
def make_rom_tree(tmp_path: Path, spec: dict[str, bytes | int]) -> dict[str, Path]:
    """Create a synthetic ROM file tree under tmp_path.
    
    spec maps relative POSIX path strings to file content:
      - bytes: written verbatim
      - int: that many bytes of b'\xAA' (deterministic filler)
    
    Preconditions: tmp_path is a writable directory; all spec keys use forward slashes.
    Postconditions: every file in spec is created; parent dirs created as needed;
                    returns a dict mapping the same keys to absolute Path objects.
    Error: raises OSError on write failure (not caught — let tests fail loudly)."""

class CrashSimulator:
    """Context manager that wraps a callable and raises OSError on the Nth call.
    
    Usage:
        with CrashSimulator(shutil.move, fail_at=2) as sim:
            sim("src", "dst")  # calls 0 and 1 succeed; call 2 raises OSError
    
    fail_at: 0-indexed call count at which OSError("simulated crash") is raised.
    Calls after fail_at: also raise (to prevent silent continuation).
    Thread-safety: not thread-safe."""
```

### Test Scenarios (U1) — `tests/test_refactor_smoke.py`

**T1.1 — Import smoke:**
Input: none. Action: `import rom_stuffer`. Expected: no ImportError; `rom_stuffer.__version__` is a string.

**T1.2 — Submodule imports:**
Action: `from rom_stuffer.guards import exclusion_reason, describe_error;
         from rom_stuffer.metrics import SessionMetrics;
         from rom_stuffer.compress import compress_roms`.
Expected: all succeed without ImportError.

**T1.3 — Module entry point:**
Action: `python -m rom_stuffer --help` (subprocess). Expected: exits 0; stdout contains "compress".

**T1.4 — Shim deprecation notice:**
Action: `python compress_roms.py --help` (subprocess). Expected: stderr contains "compatibility shim"; exits 0.

**T1.5 — Collision disambiguation preserved:**
```python
tree = make_rom_tree(tmp_path, {
    "Game.gb": 1024,
    "Game.gbc": 1024,
})
```
Action: call `compress_roms(str(source), None, str(dest), dry_run=False, recursive=False)`.
Expected: `source / "Game.zip"` exists; `source / "Game_gb.zip"` OR `source / "Game_gbc.zip"` exists (one for each).

**T1.6 — `.bin` under `psp/` refused:**
```python
tree = make_rom_tree(tmp_path, {"psp/game.bin": 512 * 1024})
```
Action: call `exclusion_reason(path, ".bin", 512*1024, source)`.
Expected: returns a non-None string mentioning "disc-based system".

**T1.7 — `.bin` under `megadrive/` accepted:**
```python
tree = make_rom_tree(tmp_path, {"megadrive/Sonic.bin": 1024 * 1024})
```
Action: `exclusion_reason(path, ".bin", 1024*1024, source)`. Expected: returns None.

**T1.8 — resume-after-crash:**
```python
tree = make_rom_tree(tmp_path / "src", {"a.gba": 1024, "b.gba": 1024, "c.gba": 1024})
```
Action: call `compress_roms(src, ".gba", dest)` with a crash injected after first file
using `CrashSimulator`; then call `compress_roms(src, ".gba", dest, resume=True)`.
Expected: all three files present as zips; journal shows all three done.

---

## U2: CLI Subcommands + No-Arg Interactive Menu

**Dependencies:** U1.
**Execution wave:** 1 (parallel with U3, U11).
**Files modified:** `rom_stuffer/cli.py` (replace U1 stub).
**Files created:** `tests/test_cli.py`.

### Function Signatures and Contracts

```python
def main() -> None:
    """Top-level CLI entry point.
    
    Precondition: called from __main__ or rom_stuffer.py.
    Postcondition: routes to the correct handler based on argv; exits via sys.exit
                   on critical errors; returns normally on success.
    Error: argparse handles --help and unknown flags; subcommand handlers raise
           SystemExit on path validation failures (as before)."""

def _build_parser() -> argparse.ArgumentParser:
    """Construct and return the ArgumentParser with shared parent + subparsers.
    
    Precondition: none.
    Postcondition: returned parser has subparsers "compress" and "dedup"; the shared
                   parent defines -s/--source, -d/--dest, -sd/--sdcard, --dry-run,
                   --theme, --resume, --fresh. The compress subparser adds -t/--type,
                   --no-recursive, -l/--level. The dedup subparser adds --keeper-order,
                   --protect, --per-system, --min-size, --interactive, --hard-delete,
                   --apply-plan. See Appendix C for full spec.
    Error: never raises; returns a fully configured parser."""

def _interactive_menu() -> None:
    """Display the themed no-arg menu and route to the chosen handler.
    
    Precondition: called when sys.argv contains only the script name (no args).
    Postcondition: prompts user for theme, then for action (1=Compress, 2=Find
                   duplicates, 3=Both); calls the corresponding handler with
                   interactively gathered paths. Loops until valid input.
    Error: Ctrl-C / KeyboardInterrupt prints a goodbye and exits 0."""

def _run_compress(args: argparse.Namespace) -> None:
    """Route parsed args to compress_roms().
    
    Precondition: args has source, dest (may be None for interactive fill-in),
                  type, sdcard, dry_run, no_recursive, level, resume, fresh.
    Postcondition: calls compress_roms with the same parameter mapping as the
                   original __main__ block; theme is applied before the call.
    Error: propagates SystemExit from compress_roms."""

def _run_dedup(args: argparse.Namespace) -> None:
    """Route parsed args to the dedup flow (stub in U2, wired in U7/U8).
    
    Precondition: args has source, dest, dry_run, keeper_order, protect,
                  per_system, min_size, interactive, hard_delete, apply_plan.
    Postcondition (U2 stub): prints "[dedup stub] not yet implemented" and returns.
                  (U7/U8): runs full dedup flow.
    Error: stub never raises."""

def _run_both(args: argparse.Namespace) -> None:
    """Route to dedup-then-compress (stub in U2, wired in U10).
    
    Postcondition (U2 stub): prints "[both stub] not yet implemented" and returns.
                  (U10): runs dedup to completion, then compresses survivors."""
```

### No-Arg Menu Pseudocode

```
1. If len(sys.argv) == 1:
   a. Prompt theme (same prompt as original interactive mode)
   b. apply_theme(choice)
   c. print_header()
   d. Print menu:
        "What would you like to do?"
        "  [1] Compress ROMs"
        "  [2] Find duplicates"
        "  [3] Both  (de-duplicate, then compress)"
   e. choice = IntPrompt.ask("Choose", choices=["1","2","3"])
   f. source = Prompt.ask("[accent]Source[/accent] directory")
   g. dest   = Prompt.ask("[accent]Destination[/accent] directory")
   h. dry_run = Confirm.ask("Dry run?", default=False)
   i. If choice == 1: build args namespace, call _run_compress
      If choice == 2: build args namespace, call _run_dedup
      If choice == 3: build args namespace, call _run_both
2. Else: parse with _build_parser() and route by subcommand
```

### Test Scenarios (U2) — `tests/test_cli.py`

Use `subprocess.run` or `unittest.mock.patch("sys.argv", [...])` + `main()`.

**T2.1 — compress subcommand routes correctly:**
Action: mock argv as `["rom_stuffer.py", "compress", "-s", "/tmp/src", "-d", "/tmp/dst"]`.
Expected: `_run_compress` called (monkeypatch it); `_run_dedup` not called.

**T2.2 — dedup subcommand routes to stub:**
Action: mock argv as `["rom_stuffer.py", "dedup", "-s", "/tmp/src", "-d", "/tmp/dst"]`.
Expected: `_run_dedup` called; no exception.

**T2.3 — --help lists subcommands:**
Action: `subprocess.run(["python", "rom_stuffer.py", "--help"])`.
Expected: stdout contains "compress" and "dedup"; exit 0.

**T2.4 — unknown subcommand errors cleanly:**
Action: `subprocess.run(["python", "rom_stuffer.py", "frobnicate"])`.
Expected: exit != 0; stderr mentions unrecognized or invalid choice.

**T2.5 — menu choice 1 routes to compress (integration):**
Using input injection for interactive menu (mock `Prompt.ask` and `IntPrompt.ask`).
Inputs: theme="zelda", choice=1, source=valid_dir, dest=valid_dir, dry_run=True.
Expected: `compress_roms` called with dry_run=True; no dedup call.

---

## U3: Logical-Content Hashing

**Dependencies:** U1.
**Execution wave:** 1 (parallel with U2, U11).
**Files created:** `rom_stuffer/hashing.py`, `tests/test_hashing.py`.

### Function Signatures and Contracts

```python
HASH_CHUNK_BYTES: int = 1 * 1024 * 1024   # 1 MB streaming chunk
FINGERPRINT_PARTIAL_BYTES: int = 64 * 1024  # 64 KB for raw partial read

def logical_size(path: Path) -> int:
    """Return the uncompressed content size in bytes.
    
    Precondition: path exists and is readable.
    Postcondition:
      - .zip: sum of ZipInfo.file_size across all entries (uncompressed total).
      - other: path.stat().st_size.
      - Returns 0 for an empty zip (no entries).
    Error: propagates OSError; propagates zipfile.BadZipFile for corrupt zips.
           Callers must catch and record as a skip/error."""

def quick_fingerprint(path: Path) -> tuple[str, object]:
    """Return a cheap pre-filter fingerprint; same-content files must collide.
    
    Precondition: path exists and is readable.
    Postcondition:
      - Returns a 2-tuple (container_tag, data) where:
          container_tag = "zip" for .zip files, "raw" for all others.
          For "zip": data = tuple(int, ...) of each entry's CRC-32 (from central
              directory, NO decompression), entries sorted by ZipInfo.filename.
          For "raw": data = (crc32_first, crc32_last) where crc32_first is
              zlib.crc32 of the first FINGERPRINT_PARTIAL_BYTES of the file,
              crc32_last is zlib.crc32 of the last FINGERPRINT_PARTIAL_BYTES
              (same block as first if file <= FINGERPRINT_PARTIAL_BYTES).
      - Two files with DIFFERENT logical content SHOULD produce different
        fingerprints (collision possible but rare — SHA-256 confirms).
      - Cross-container fingerprints (zip vs raw) NEVER collide by construction
        (different container_tag). The detection pipeline handles this correctly.
    Error: propagates OSError, BadZipFile."""

def content_sha256(path: Path) -> str:
    """Return the hex SHA-256 of the logical (uncompressed) ROM content.
    
    Precondition: path exists and is readable.
    Postcondition:
      - For a raw file: SHA-256 of the file's bytes streamed in HASH_CHUNK_BYTES chunks.
      - For a .zip: entries sorted by ZipInfo.filename; each entry's decompressed
          bytes streamed via ZipFile.open() in HASH_CHUNK_BYTES chunks and fed into
          a single sha256 accumulator in order. Never extracted to disk.
      - KEY INVARIANT: content_sha256("game.gba") == content_sha256("game.zip")
          when game.zip contains exactly game.gba (one entry, same bytes).
      - Returns a 64-character lowercase hex string.
    Error: propagates OSError, BadZipFile. Caller must catch and record."""
```

### Algorithm Pseudocode

#### `logical_size(path)`
```
1. If path.suffix.lower() == ".zip":
   a. with zipfile.ZipFile(path, "r") as zf:
      return sum(zi.file_size for zi in zf.infolist())
2. Else:
   return path.stat().st_size
```

#### `quick_fingerprint(path)`
```
1. If path.suffix.lower() == ".zip":
   a. with ZipFile(path, "r") as zf:
      entries = sorted(zf.infolist(), key=lambda z: z.filename)
      crcs = tuple(z.CRC for z in entries)
   b. return ("zip", crcs)
2. Else:
   a. sz = path.stat().st_size
   b. with open(path, "rb") as f:
      first_chunk = f.read(FINGERPRINT_PARTIAL_BYTES)
      if sz > FINGERPRINT_PARTIAL_BYTES:
          f.seek(max(0, sz - FINGERPRINT_PARTIAL_BYTES))
          last_chunk = f.read(FINGERPRINT_PARTIAL_BYTES)
      else:
          last_chunk = first_chunk
   c. return ("raw", (zlib.crc32(first_chunk), zlib.crc32(last_chunk)))
```

#### `content_sha256(path)`
```
1. h = hashlib.sha256()
2. If path.suffix.lower() == ".zip":
   a. with ZipFile(path, "r") as zf:
      entries = sorted(zf.infolist(), key=lambda z: z.filename)
      for entry in entries:
          with zf.open(entry) as stream:
              while True:
                  chunk = stream.read(HASH_CHUNK_BYTES)
                  if not chunk: break
                  h.update(chunk)
3. Else:
   a. with open(path, "rb") as f:
      while True:
          chunk = f.read(HASH_CHUNK_BYTES)
          if not chunk: break
          h.update(chunk)
4. return h.hexdigest()
```

### Test Scenarios (U3) — `tests/test_hashing.py`

**T3.1 — raw vs zip SHA-256 equality:**
```python
content = b"SNES ROM DATA " * 512  # 7168 bytes
tree = make_rom_tree(tmp_path, {"game.smc": content})
# Also create a zip containing game.smc with the same bytes
import zipfile
zip_path = tmp_path / "game.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("game.smc", content)
```
Action: `content_sha256(tmp_path / "game.smc")` and `content_sha256(zip_path)`.
Expected: both return the same 64-char hex string.

**T3.2 — different content yields different SHA-256:**
```python
tree = make_rom_tree(tmp_path, {"a.gba": b"ROM_A" * 100, "b.gba": b"ROM_B" * 100})
```
Action: `content_sha256(path_a) != content_sha256(path_b)`. Expected: True.

**T3.3 — logical_size for raw vs zip:**
content = b"X" * 8192
Expected: `logical_size(raw_path) == 8192` and `logical_size(zip_path) == 8192`.

**T3.4 — zip hashing never writes temp files:**
Before call: note `os.listdir(tmp_path)`. After `content_sha256(zip_path)`: same listing.

**T3.5 — large file stays memory-bounded (streaming):**
Make a 32MB raw file (int 32*1024*1024 in make_rom_tree). Call `content_sha256`.
Expected: completes without MemoryError; returns a 64-char string.
(Do not assert peak memory explicitly — assert the function returns and does not write temp files.)

**T3.6 — unreadable file raises OSError:**
Action: `content_sha256(Path("/nonexistent/path.gba"))`.
Expected: raises `OSError` (or subclass); does not return a value.

**T3.7 — corrupt zip raises BadZipFile:**
Write 50 bytes of garbage to a `.zip` file.
Action: `content_sha256(corrupt_path)`. Expected: raises `zipfile.BadZipFile`.

---

## U4: Duplicate Detection Pipeline

**Dependencies:** U1, U3.
**Execution wave:** 2.
**Files created:** `rom_stuffer/dedup.py` (detection portion), `tests/test_dedup_detect.py`.
**Note:** `dedup.py` is extended by U5 (keeper), U8 (executor). Create the file here with
detection only; do not implement functions belonging to other units.

### New Types

```python
# rom_stuffer/dedup.py

from dataclasses import dataclass, field

@dataclass
class DedupOptions:
    """Runtime configuration for a dedup session.
    
    All path fields are absolute. keeper_order and protect contain folder name
    substrings matched case-insensitively against path components. min_size is
    in bytes and defaults to 0 (no filtering)."""
    source: Path
    dest: Path
    dry_run: bool = False
    recursive: bool = True
    per_system: bool = False
    min_size: int = 0
    keeper_order: list[str] = field(default_factory=list)
    protect: list[str] = field(default_factory=list)
    interactive: bool = False
    hard_delete: bool = False
    apply_plan_path: Path | None = None
```

### Function Signatures and Contracts

```python
def detect_duplicates(
    options: DedupOptions,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, list[Path]]:
    """Scan source, find byte-identical ROM files, return duplicate groups.
    
    Preconditions:
      - options.source exists and is a directory.
      - options.dest may or may not exist.
    Postconditions:
      - Returns {sha256_hex: [path, path, ...]} for every group with >= 2 members.
      - Paths are absolute. All paths in a group have equal logical content.
      - Files refused by exclusion_reason (BIOS, disc) are never in any group.
      - Files smaller than options.min_size are skipped.
      - If options.per_system=True, only files sharing the same direct child folder
        of source (i.e. the system folder) are compared.
      - Singleton files (unique logical size or unique fingerprint) are never
        content-hashed.
    Error: OSError / BadZipFile on individual files are caught; the file is added to
           a skipped list (returned via a second value — see below); detection continues.
    Note: this function returns (groups, skipped_files) as a tuple:
      groups: dict[str, list[Path]]
      skipped_files: list[dict]  # [{"file": str, "reason": str}]
    """

def _enumerate_candidates(
    options: DedupOptions,
) -> tuple[list[Path], list[dict]]:
    """Enumerate ROM candidates, applying guards and min_size filter.
    
    Precondition: options.source is a readable directory.
    Postcondition:
      - Returns (candidates, skipped) where candidates is a list of absolute Paths
        to files that passed exclusion_reason and min_size.
      - skipped contains {"file": str, "reason": str} for every excluded path.
      - Uses source.rglob("*") if options.recursive else source.glob("*").
    Error: individual OSError caught and added to skipped."""

def _bucket_by_size(
    candidates: list[Path],
) -> dict[int, list[Path]]:
    """Group candidates by logical_size.
    
    Precondition: candidates is a list of readable Paths.
    Postcondition: returns {logical_size: [path, ...]}; files where logical_size
                   raises are excluded (not in any bucket).
    Error: OSError / BadZipFile per file is caught and the file is dropped."""

def _apply_fingerprint(
    size_bucket: list[Path],
) -> list[list[Path]]:
    """Pre-filter a size bucket into fingerprint collision groups.
    
    Precondition: len(size_bucket) >= 2; all files exist.
    Postcondition:
      - If bucket is HOMOGENEOUS (all zip or all raw): group by quick_fingerprint;
        return only groups with >= 2 members.
      - If bucket is MIXED (zip and raw both present): return [size_bucket] (all
        proceed to SHA-256; fingerprint cannot compare cross-container).
      - Groups with exactly 1 member are dropped.
    Error: quick_fingerprint errors per file are caught; that file is dropped."""

def _confirm_sha256(
    candidates: list[Path],
) -> dict[str, list[Path]]:
    """Compute content_sha256 and group by hash.
    
    Precondition: candidates has >= 2 files, all pre-filtered by fingerprint or size.
    Postcondition: returns {sha256_hex: [path, ...]} for groups with >= 2 members.
    Error: content_sha256 errors per file are caught; that file is dropped."""
```

### Detection Pipeline Pseudocode

```
detect_duplicates(options):
1. candidates, skipped = _enumerate_candidates(options)
2. size_buckets = _bucket_by_size(candidates)
3. sha256_groups: dict[str, list[Path]] = defaultdict(list)
4. For each (sz, paths) in size_buckets.items():
   a. If len(paths) < 2: continue  # unique size, never read
   b. collision_groups = _apply_fingerprint(paths)
   c. For each group in collision_groups:
      i. If len(group) < 2: continue
      ii. confirmed = _confirm_sha256(group)
      iii. For h, members in confirmed.items():
             sha256_groups[h].extend(members)
5. # Deduplicate paths within each hash group (a path may appear in multiple
   # fingerprint groups if quick_fingerprint had different representations)
   result = {h: list(dict.fromkeys(ps))  # preserve order, deduplicate
             for h, ps in sha256_groups.items() if len(ps) >= 2}
6. return result, skipped

_enumerate_candidates(options):
1. candidates = []
2. skipped = []
3. scan_iter = options.source.rglob("*") if options.recursive else options.source.glob("*")
4. For each p in scan_iter:
   try:
     if not p.is_file(): continue
     ext = p.suffix.lower()
     if ext not in SUPPORTED_EXTENSIONS:
         skipped.append({"file": str(p.name), "reason": f"Unsupported: {p.suffix}"})
         continue
     sz = p.stat().st_size
     size_for_guard = sz if ext == ".bin" else None
     reason = exclusion_reason(p, ext, size_for_guard, options.source)
     if reason:
         skipped.append({"file": str(p.name), "reason": reason})
         continue
     if sz < options.min_size:
         skipped.append({"file": str(p.name),
                         "reason": f"Below min-size ({format_size(options.min_size)})"})
         continue
     candidates.append(p)
   except OSError as e:
     skipped.append({"file": str(p.name), "reason": f"Unreadable: {describe_error(e)}"})
5. If options.per_system:
   # Group by direct child of source; only compare within same child folder.
   # Replace candidates with a filtered list: retain only candidates whose
   # source-relative first path component appears >= 2 times.
   from collections import Counter
   system_counts = Counter(p.relative_to(options.source).parts[0]
                           for p in candidates if len(p.relative_to(options.source).parts) > 0)
   candidates = [p for p in candidates
                 if system_counts[p.relative_to(options.source).parts[0]] >= 2]
6. return candidates, skipped
```

### Test Scenarios (U4) — `tests/test_dedup_detect.py`

**T4.1 — raw+raw identical files grouped:**
```python
content = b"GBA_ROM_CONTENT" * 256
tree = make_rom_tree(tmp_path / "src", {
    "gba/game.gba": content,
    "gba/backup/game.gba": content,
})
```
Action: `groups, skipped = detect_duplicates(DedupOptions(source, dest))`.
Expected: `len(groups) == 1`; the single group has exactly 2 paths containing "game.gba".

**T4.2 — raw+zip identical content grouped:**
Create raw `game.gba` and `game.zip` containing same bytes via zipfile.
Action: detect_duplicates. Expected: 1 group with both paths.

**T4.3 — zip+zip identical content grouped:**
Create two zips of same raw bytes via zipfile. Action: detect_duplicates.
Expected: 1 group with both zip paths.

**T4.4 — singletons never content-hashed:**
Monkeypatch `content_sha256` to raise if called.
```python
tree = make_rom_tree(tmp_path / "src", {"a.gba": b"AAA"*100, "b.smc": b"BBB"*200})
```
Action: detect_duplicates. Expected: no exception (content_sha256 not called); 0 groups.

**T4.5 — three-way duplicate set:**
```python
content = b"TRIPLE" * 512
tree = make_rom_tree(tmp_path / "src", {
    "a/game.nes": content, "b/game.nes": content, "c/game.nes": content
})
```
Expected: 1 group with 3 paths.

**T4.6 — BIOS never appears:**
```python
tree = make_rom_tree(tmp_path / "src", {
    "bios/scph1001.bin": b"BIOS" * 128,
    "psx/game.bin": b"BIOS" * 128,  # same content, disc system
    "gba/game.gba": b"ROM" * 100,
})
```
Expected: 0 groups; bios and psx/game.bin both in skipped.

**T4.7 — unique library yields zero groups:**
```python
tree = make_rom_tree(tmp_path / "src", {
    "a.gba": b"A"*512, "b.gba": b"B"*512, "c.smc": b"C"*512
})
```
Expected: 0 groups; content_sha256 not called (all unique sizes).

**T4.8 — per_system limits comparison:**
```python
content = b"SAME" * 256
tree = make_rom_tree(tmp_path / "src", {
    "gba/game.gba": content,
    "snes/game.smc": content,  # same content but different extension anyway
})
# For per_system to be meaningful, use same extension in different system folders:
tree = make_rom_tree(tmp_path / "src2", {
    "gba/game.gba": content,
    "gba_backup/game.gba": content,
    "snes/other.smc": b"SNES" * 256,
})
```
Action with `per_system=False`: 1 group (gba vs gba_backup).
Action with `per_system=True`: 0 groups (gba and gba_backup are different top-level dirs; each has only 1 file of that size).

---

## U5: Keeper Rules + Global Knobs

**Dependencies:** U4.
**Execution wave:** 3 (parallel with U6).
**Files modified:** `rom_stuffer/dedup.py` (add keeper functions).
**Files created:** `tests/test_keeper.py`.

### Keeper Heuristic — Ordered Rule List

Given a group of duplicate paths, `select_keeper` returns the single path to preserve.
The selection is deterministic: build a sort key for each path; the path with the
LOWEST key wins. Rules are applied in order; the first rule that produces a different
key value between two paths determines the winner. Lower key value = more preferred.

**Rule 0 (Protect flag):** `0 if any protected folder name in {c.lower() for c in p.parts} else 1`.
A path inside a --protect folder is maximally preferred. Multiple protect folders: any
match counts.

**Rule 1 (Keeper order):** If `--keeper-order` is specified as a comma-separated list
of folder name substrings, compute the index of the FIRST matching folder in a path
(searching p.parts case-insensitively). Paths with a match at index i score i; paths
with no match score `len(keeper_order)` (worst). Lower index = more preferred.

**Rule 2 (Not a junk folder):** `0 if NOT in junk folder, else 1`.
Junk folder names (case-insensitive, matched against any component of the path
relative to source): `dupes`, `dupe`, `duplicates`, `duplicate`, `backup`, `backups`,
`copies`, `copy`, `_dupes`, `_backup`.

**Rule 3 (Not a junk name):** `0 if clean name, else 1`.
Junk name: `p.stem` (case-insensitive) ends with ` (1)`, ` (2)`, ` copy`, `-copy`,
`_copy`, `- copy`, ` - copy`, or matches the pattern `r" \(\d+\)$"` (trailing
` (N)` for any integer N).

**Rule 4 (No-Intro region tag):** `0 if stem has a region tag, else 1`.
Region tag: `p.stem` contains a substring matching `r"\((USA|Europe|Japan|World|En|Fr|De|Es|It|Pt|Nl|Sv|No|Da|Ko|Zh|Ru|Pl)[^)]*\)"`.
A No-Intro-tagged name is PREFERRED (rule value 0).

**Rule 5 (Compressed):** `0 if p.suffix.lower() == ".zip" else 1`.
The compressed copy is preferred (it is smaller; keeping it avoids a re-compression step).

**Rule 6 (Path depth):** `len(p.relative_to(source).parts)`.
Shallower paths (fewer components relative to source) are preferred.

**Rule 7 (Alphabetical tie-break):** `str(p)`.
Deterministic: the lexicographically first path wins if all prior rules are tied.

### Function Signatures and Contracts

```python
def select_keeper(
    paths: list[Path],
    options: DedupOptions,
) -> Path:
    """Return the path in `paths` that the keeper heuristic selects.
    
    Preconditions:
      - len(paths) >= 2; all paths are absolute; all have equal logical content.
      - options.source is a prefix of all paths.
    Postconditions:
      - Returns exactly one Path from `paths`.
      - The result is deterministic: same inputs always produce the same result.
      - If a protected path is in `paths`, it is always returned (Rule 0).
      - If --keeper-order is set, the highest-priority matching path wins (Rule 1).
      - Tie-breaking is alphabetical (Rule 7); the result never changes across runs.
    Error: never raises (all fields are safe to access)."""

def _keeper_sort_key(
    path: Path,
    options: DedupOptions,
) -> tuple:
    """Compute the sort key for `path` using the 8-rule keeper heuristic.
    
    Precondition: path is absolute; options.source is a prefix.
    Postcondition: returns an 8-tuple; sorting ascending puts the preferred path first.
    Error: never raises."""

def _has_no_intro_region(stem: str) -> bool:
    """Return True if stem contains a No-Intro-style region parenthetical.
    
    Precondition: stem is the filestem string (no extension, no trailing dot).
    Postcondition: True iff stem matches the region-tag regex (see rule 4 above).
    Error: never raises."""

def _is_junk_name(stem: str) -> bool:
    """Return True if stem ends with a junk-copy suffix.
    
    Precondition: stem is the filestem.
    Postcondition: True iff stem matches any junk-name pattern (rule 3 above).
    Error: never raises."""

def _is_junk_folder(path: Path, source: Path) -> bool:
    """Return True if any component of path (relative to source) is a junk folder name.
    
    Precondition: source is a prefix of path.
    Postcondition: True iff any part of path.relative_to(source).parts matches
                   the junk folder set (case-insensitive).
    Error: never raises."""
```

### Algorithm Pseudocode

```
select_keeper(paths, options):
1. keyed = [((_keeper_sort_key(p, options)), p) for p in paths]
2. keyed.sort(key=lambda x: x[0])
3. return keyed[0][1]

_keeper_sort_key(path, options):
1. rel = path.relative_to(options.source)
2. parts_lower = {c.lower() for c in path.parts}
3. r0 = 0 if any(pf.lower() in parts_lower for pf in options.protect) else 1
4. r1 = len(options.keeper_order)  # default: no match
   for i, folder in enumerate(options.keeper_order):
       if any(folder.lower() == c.lower() for c in path.parts):
           r1 = i; break
5. r2 = 1 if _is_junk_folder(path, options.source) else 0
6. r3 = 1 if _is_junk_name(path.stem) else 0
7. r4 = 0 if _has_no_intro_region(path.stem) else 1
8. r5 = 0 if path.suffix.lower() == ".zip" else 1
9. r6 = len(rel.parts)
10. r7 = str(path)
11. return (r0, r1, r2, r3, r4, r5, r6, r7)
```

### Test Scenarios (U5) — `tests/test_keeper.py`

**T5.1 — compressed preferred over raw:**
```python
paths = [Path("/src/game.gba"), Path("/src/game.zip")]
# Assume same logical content
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"))
```
Expected: `select_keeper(paths, opts) == Path("/src/game.zip")` (Rule 5).

**T5.2 — protected folder always wins:**
```python
paths = [Path("/src/game.zip"), Path("/src/golden/game.zip")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"), protect=["golden"])
```
Expected: `select_keeper(paths, opts) == Path("/src/golden/game.zip")`.

**T5.3 — keeper-order overrides default:**
```python
paths = [Path("/src/gba/game.gba"), Path("/src/priority/game.gba")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"), keeper_order=["priority"])
```
Expected: returns the path containing "priority".

**T5.4 — junk folder de-prioritised:**
```python
paths = [Path("/src/dupes/game.gba"), Path("/src/gba/game.gba")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"))
```
Expected: `select_keeper(paths, opts) == Path("/src/gba/game.gba")` (Rule 2).

**T5.5 — junk name de-prioritised:**
```python
paths = [Path("/src/game (1).gba"), Path("/src/game.gba")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"))
```
Expected: returns `Path("/src/game.gba")` (Rule 3).

**T5.6 — No-Intro name preferred:**
```python
paths = [Path("/src/sonic.gba"), Path("/src/Sonic the Hedgehog (USA).gba")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"))
```
Expected: returns the No-Intro path (Rule 4).

**T5.7 — shallower path preferred (tie-break):**
```python
paths = [Path("/src/a/b/game.gba"), Path("/src/a/game.gba")]
opts = DedupOptions(source=Path("/src"), dest=Path("/dst"))
```
Expected: returns `/src/a/game.gba` (Rule 6: depth 2 < depth 3).

**T5.8 — alphabetical tie-break is deterministic:**
```python
paths = [Path("/src/z/game.gba"), Path("/src/a/game.gba")]
# Same depth, no other rules apply.
```
Expected: returns `/src/a/game.gba` every time (Rule 7).

**T5.9 — min_size knob (filtering done in detect; keeper not affected):**
Verify that if all paths have depth=1 and no other distinctions, the alphabetically
first path always wins (regression: ensure sort is stable and deterministic).

---

## U6: Dedup Plan + Hash Index Persistence

**Dependencies:** U4, U5.
**Execution wave:** 3 (parallel with U5; but U5 must complete before U6 can wire the
keeper into plan generation — sequence U5 then U6 if doing serial execution).
**Files created:** `rom_stuffer/planfile.py`, `tests/test_planfile.py`.

### Data Types

```python
# rom_stuffer/planfile.py

from dataclasses import dataclass, field
from pathlib import Path

DEDUP_PLAN_FILENAME: str = ".rom_stuffer_dedup_plan.txt"
HASH_INDEX_FILENAME: str = ".rom_stuffer_hash_index.json"

@dataclass
class DedupGroup:
    """One set of byte-identical files: one keeper, N-1 removals.
    
    All paths are absolute. sha256 is the 64-char hex content hash.
    reclaimed_bytes is the sum of stored (on-disk) sizes of all removals.
    skipped=True means the executor ignores this group."""
    sha256: str
    keeper: Path
    removals: list[Path]
    reclaimed_bytes: int
    skipped: bool = False

@dataclass
class DedupPlan:
    """A complete dedup session plan: metadata + list of groups.
    
    source is the absolute source directory path. created_at is ISO-8601 UTC.
    version must equal PLAN_VERSION for load_plan to accept it."""
    version: int
    source: Path
    created_at: str
    groups: list[DedupGroup]

PLAN_VERSION: int = 1

@dataclass
class HashRecord:
    """Per-file entry in the hash index.
    
    path is relative to source (POSIX separators). sha256 is 64-char hex.
    logical_size is the uncompressed content size. stored_size is on-disk bytes."""
    path: str
    sha256: str
    logical_size: int
    stored_size: int

HashIndex = dict[str, HashRecord]  # keyed by POSIX relative path string
```

### Function Signatures and Contracts

```python
def build_plan(
    groups: dict[str, list[Path]],
    options: DedupOptions,
) -> DedupPlan:
    """Construct a DedupPlan from detection output + keeper selection.
    
    Preconditions:
      - groups is the dict returned by detect_duplicates (sha256 → paths).
      - options.source is a prefix of all paths.
    Postconditions:
      - Returns a DedupPlan with one DedupGroup per sha256 entry.
      - Each group's keeper is selected by select_keeper(paths, options).
      - Each group's removals is [p for p in paths if p != keeper].
      - reclaimed_bytes = sum(p.stat().st_size for p in removals).
        On OSError for stat, use 0 for that file (non-fatal).
      - created_at is UTC now formatted as "%Y-%m-%dT%H:%M:%SZ".
      - Groups are sorted by reclaimed_bytes descending (largest savings first).
    Error: never raises (per-file stat errors are swallowed)."""

def save_plan(plan: DedupPlan, dest: Path) -> Path:
    """Serialise plan to a human-readable text file in dest.
    
    Preconditions: dest exists and is writable.
    Postconditions:
      - Writes dest / DEDUP_PLAN_FILENAME in the format described in Appendix B.
      - Returns the written path.
      - Atomic write: write to .tmp, then replace. Uses utf-8 encoding.
    Error: propagates OSError on write failure."""

def load_plan(dest: Path) -> DedupPlan:
    """Parse and return a DedupPlan from dest / DEDUP_PLAN_FILENAME.
    
    Precondition: dest / DEDUP_PLAN_FILENAME exists.
    Postconditions:
      - Parses the text format (see Appendix B parse rules).
      - Groups marked SKIP are loaded with skipped=True.
      - KEEP/REMOVE paths are resolved to absolute Paths (joined with source).
      - Returns a valid DedupPlan.
    Error: raises ValueError with a descriptive message if format is invalid,
           version mismatch, or the file is missing. Never deletes or modifies
           files on load failure."""

def save_hash_index(
    index: HashIndex,
    dest: Path,
) -> Path:
    """Write the hash index to dest / HASH_INDEX_FILENAME as JSON.
    
    Preconditions: dest exists and is writable.
    Postconditions:
      - Writes JSON conforming to Appendix A schema; atomic write (.tmp + replace).
      - Returns the written path.
    Error: propagates OSError."""

def load_hash_index(dest: Path) -> HashIndex:
    """Load and return a HashIndex from dest / HASH_INDEX_FILENAME.
    
    Preconditions: file exists.
    Postconditions: returns dict of POSIX-relative path → HashRecord.
    Error: raises ValueError on schema mismatch; raises OSError if unreadable."""

def build_hash_index(
    candidates: list[Path],
    source: Path,
    sha256_map: dict[str, str],
) -> HashIndex:
    """Build a HashIndex from the enumerated candidates and pre-computed hashes.
    
    Preconditions:
      - candidates: all paths that were enumerated (including non-duplicates).
      - sha256_map: {str(path) → sha256_hex} for every candidate that was hashed.
        Paths that were eliminated before SHA-256 (size singletons) will have no entry.
      - source: the scan root.
    Postconditions:
      - For each candidate: record = HashRecord(path=relative POSIX,
          sha256=sha256_map.get(str(p), ""),  # empty if not hashed
          logical_size=logical_size(p),
          stored_size=p.stat().st_size).
      - On OSError for any individual file: stored_size = 0, logical_size = 0.
    Error: never raises (all errors per-file are swallowed)."""
```

### Save Plan Pseudocode

```
save_plan(plan, dest):
1. lines = []
2. lines.append("# ROM Stuffer Dedup Plan")
3. lines.append(f"# version: {plan.version}")
4. lines.append(f"# source: {plan.source}")
5. lines.append(f"# created: {plan.created_at}")
6. lines.append("# Edit: change KEEP/REMOVE, or add '# SKIP' before a group header.")
7. lines.append("")
8. For i, group in enumerate(plan.groups, start=1):
   a. if group.skipped: lines.append("# SKIP")
   b. lines.append(f"--- GROUP {i}/{len(plan.groups)} ---")
   c. lines.append(f"sha256: {group.sha256}")
   d. lines.append(f"reclaims: {format_size(group.reclaimed_bytes)}")
   e. lines.append(f"KEEP:   {group.keeper.relative_to(plan.source).as_posix()}")
   f. For removal in group.removals:
      lines.append(f"REMOVE: {removal.relative_to(plan.source).as_posix()}")
   g. lines.append("")
9. Write "\n".join(lines) to tmp file; fsync; replace.
10. return dest / DEDUP_PLAN_FILENAME

load_plan(dest):
1. text = read file as utf-8
2. Split into lines; strip trailing whitespace from each.
3. Parse header: extract version, source, created_at from "# key: value" lines
   before the first "--- GROUP" line.
4. Validate version == PLAN_VERSION (else raise ValueError).
5. groups = []
6. current_group = None; current_skip = False
7. For each line:
   a. If line starts with "#":
      - If "# SKIP" (case-insensitive stripped): current_skip = True
      - Other comments: skip
   b. If line matches r"^--- GROUP \d+/\d+ ---$":
      - If current_group is not None: groups.append(current_group)
      - current_group = DedupGroup(sha256="", keeper=None, removals=[], 
                                    reclaimed_bytes=0, skipped=current_skip)
      - current_skip = False
   c. If line starts with "sha256: ": current_group.sha256 = rest
   d. If line starts with "reclaims: ": ignore (recalculated on load)
   e. If line starts with "KEEP:   " or "KEEP: ": 
      - path_rel = line[len("KEEP:"):].strip()
      - current_group.keeper = Path(source) / Path(path_rel)
   f. If line starts with "REMOVE: ":
      - path_rel = line[len("REMOVE:"):].strip()
      - current_group.removals.append(Path(source) / Path(path_rel))
8. If current_group is not None: groups.append(current_group)
9. Recalculate reclaimed_bytes for each group: try stat each removal; sum stored sizes.
10. return DedupPlan(version, source, created_at, groups)
```

### Test Scenarios (U6) — `tests/test_planfile.py`

**T6.1 — round-trip save/load preserves groups:**
Build a DedupPlan with 2 groups (create Path objects to tmp_path files).
`save_plan(plan, dest)`. `loaded = load_plan(dest)`.
Expected: `loaded.groups[0].keeper == plan.groups[0].keeper`;
`loaded.groups[0].removals == plan.groups[0].removals`;
`loaded.groups[0].sha256 == plan.groups[0].sha256`.

**T6.2 — hand-edited keeper is honoured:**
Save a plan. Open the file, swap the KEEP and a REMOVE line. Call `load_plan(dest)`.
Expected: loaded group's keeper is the previously-REMOVE path; removals contain the
previously-KEEP path.

**T6.3 — SKIP group is loaded with skipped=True:**
Save a plan with group.skipped=False. Open the file, add `# SKIP` before the
`--- GROUP 1/2 ---` line. `load_plan(dest)`. Expected: first group has skipped=True.

**T6.4 — hash index contains both sizes:**
```python
# Create a raw GBA file and a zip of the same content
raw = tmp_path / "game.gba"; raw.write_bytes(b"ROM" * 1000)
with zipfile.ZipFile(tmp_path / "game.zip", "w") as zf:
    zf.writestr("game.gba", b"ROM" * 1000)
candidates = [raw, tmp_path / "game.zip"]
sha256_map = {str(raw): content_sha256(raw), str(tmp_path/"game.zip"): content_sha256(tmp_path/"game.zip")}
index = build_hash_index(candidates, tmp_path, sha256_map)
```
Expected: `index["game.gba"].logical_size == 3000`;
`index["game.gba"].stored_size == 3000` (raw: same);
`index["game.zip"].logical_size == 3000`;
`index["game.zip"].stored_size < 3000` (compressed: smaller).

**T6.5 — corrupt plan → ValueError, no files deleted:**
Write garbage to the plan file. `load_plan(dest)`. Expected: raises ValueError.
Assert that no file operations occurred (no files missing from tmp_path).

**T6.6 — hash index round-trip:**
`save_hash_index(index, dest)`. `loaded = load_hash_index(dest)`.
Expected: all HashRecord fields preserved; file is valid JSON.

---

## U7: TUI Plan Review / Edit / Apply

**Dependencies:** U6.
**Execution wave:** 4 (parallel with U8).
**Files created:** `rom_stuffer/review.py`, `tests/test_review.py`.
**Note:** U7 handles the TUI interaction only; the executor (actual file moves/deletes)
lives in U8. U7 returns a DedupPlan; U8 applies it.

### Function Signatures and Contracts

```python
# rom_stuffer/review.py

def review_plan(
    plan: DedupPlan,
    options: DedupOptions,
) -> DedupPlan:
    """Present the dedup plan for interactive review; return the (possibly modified) plan.
    
    Precondition: plan has >= 1 group; options.interactive controls per-group mode.
    Postconditions:
      - In non-interactive mode (default): show summary panel; prompt for accept/edit/quit.
          Accept: return plan unchanged.
          Edit: call _edit_group_loop() for selected group(s); return modified plan.
          Quit: raises SystemExit(0).
      - In interactive mode (--interactive): call _prompt_group() for each group in sequence.
      - Groups modified by the user have their keeper / removals / skipped updated.
      - The returned plan is saved via save_plan before returning (so it is persisted
        even if the caller does not explicitly save again).
    Error: KeyboardInterrupt is caught; prints goodbye; raises SystemExit(0).
           Rich markup in filenames is escaped via rich.markup.escape before display."""

def _show_summary(plan: DedupPlan) -> None:
    """Display a Rich summary panel: group count, total reclaimable bytes.
    
    Postcondition: prints a themed Panel with:
      - "N duplicate groups found"
      - "Total reclaimable: X MB"
      - Dry-run note if plan was created in dry-run mode.
    Error: never raises."""

def _show_group(group: DedupGroup, index: int, total: int) -> None:
    """Display one duplicate group in the TUI.
    
    Postcondition: prints a Rich table showing:
      - Group N/M header with sha256 (first 12 chars displayed)
      - KEEP row (highlighted in success style)
      - Each REMOVE row (muted style)
      - Reclaims: X MB
    All paths displayed as str(path); Rich markup escaped.
    Error: never raises."""

def _prompt_group(
    group: DedupGroup,
    index: int,
    total: int,
    options: DedupOptions,
) -> DedupGroup:
    """Prompt user to accept, change keeper, or skip one group.
    
    Precondition: group has >= 1 removal.
    Postcondition:
      - Displays the group via _show_group.
      - Prompts: "[a]ccept / [N] change keeper to #N / [s]kip / [q]uit"
        where N ranges from 1..len(all_paths) (keeper + removals combined, shown numbered).
      - Accept: return group unchanged.
      - Change keeper to N: swap keeper with the Nth path; update removals; return.
      - Skip: return group with skipped=True.
      - Quit: raises SystemExit(0).
    Error: invalid input re-prompts; never raises on valid input."""

def _edit_group_loop(
    plan: DedupPlan,
    options: DedupOptions,
) -> DedupPlan:
    """Allow the user to edit individual groups from the summary view.
    
    Postcondition: prompts for a group number; calls _prompt_group for that group;
                   loops until user says done. Returns modified plan.
    Error: invalid group number re-prompts."""
```

### Review Flow Pseudocode (non-interactive default)

```
review_plan(plan, options):
1. _show_summary(plan)
2. If not options.interactive:
   a. Loop:
      action = Prompt.ask("  [a]ccept all  [e]dit a group  [q]uit",
                          choices=["a", "e", "q"], default="a")
      If action == "a": break  # accept all as-is
      If action == "e": plan = _edit_group_loop(plan, options)
      If action == "q": raise SystemExit(0)
3. Else (interactive):
   For i, group in enumerate(plan.groups):
       plan.groups[i] = _prompt_group(group, i+1, len(plan.groups), options)
4. save_plan(plan, options.dest)
5. return plan
```

### Test Scenarios (U7) — `tests/test_review.py`

All tests use monkeypatching of `Prompt.ask` / `Confirm.ask` to inject input.

**T7.1 — accept-all returns plan unchanged:**
Mock `Prompt.ask` to return "a". Call `review_plan(plan, options)`.
Expected: returned plan has same groups as input plan.

**T7.2 — change keeper updates group:**
Build a plan with 1 group: keeper=path_A, removals=[path_B].
Mock Prompt.ask sequence: "e", group_number="1", "2" (change keeper to #2), "a" (accept rest).
Expected: returned plan has keeper=path_B, removals=[path_A].

**T7.3 — skip a group marks it skipped:**
Mock "e" then group "1" then "s" then "a".
Expected: group 0 has skipped=True.

**T7.4 — filename with Rich markup brackets is escaped:**
Build a group with keeper path containing "[USA]" in stem.
Mock "a". Call review_plan. Expected: no Rich MarkupError; displays correctly.

**T7.5 — pagination handles many groups:**
Build a plan with 25 groups. Mock "a".
Expected: _show_summary prints "25 duplicate groups"; review_plan returns without error.

**T7.6 — quit exits cleanly:**
Mock Prompt.ask to return "q". Call review_plan.
Expected: raises SystemExit with code 0.

---

## U8: Dedup Executor (Quarantine / Delete)

**Dependencies:** U6, U7.
**Execution wave:** 4 (parallel with U7).
**Files modified:** `rom_stuffer/dedup.py` (add executor functions).
**Files created:** `tests/test_dedup_apply.py`.

### New Types

```python
# rom_stuffer/dedup.py (add to existing file)

from dataclasses import dataclass, field

DEDUP_JOURNAL_FILENAME: str = ".rom_stuffer_dedup_journal.log"
DEDUP_BACKUP_DIRNAME: str = "dedup_backup"

@dataclass
class DedupMetrics:
    """Accumulates dedup-pass statistics for reporting.
    
    All numeric fields initialise to 0; errors to []; dry_run to False."""
    files_hashed: int = 0
    files_skipped: int = 0
    groups_found: int = 0
    files_removed: int = 0
    bytes_reclaimed: int = 0
    errors: list = field(default_factory=list)  # [{"file": str, "error": str}]
    dry_run: bool = False
```

### Function Signatures and Contracts

```python
def apply_plan(
    plan: DedupPlan,
    options: DedupOptions,
    metrics: DedupMetrics,
) -> None:
    """Apply an approved dedup plan: quarantine or delete each removal.
    
    Preconditions:
      - plan.source == options.source (checked; raises ValueError if not).
      - options.dest exists or can be created.
      - options.dry_run: if True, counts only, no moves/deletes.
      - options.hard_delete: if True, use unlink; else move to quarantine.
    Postconditions:
      - For each non-skipped group's removals: move to quarantine OR delete.
      - Quarantine target: options.dest / DEDUP_BACKUP_DIRNAME / rel_path
          where rel_path = removal.relative_to(options.source).
      - Keeper is NEVER touched (invariant enforced by assertion).
      - Each removal is journalled on completion (append-only, flushed per file).
      - metrics.files_removed and metrics.bytes_reclaimed are updated.
      - Failures on individual files are recorded in metrics.errors and do not
          abort the batch.
      - On completion, the dedup journal is fsynced and closed.
    Error: ValueError if plan.source != options.source. Per-file OSError caught
           and recorded; does not propagate."""

def _load_dedup_journal(dest: Path) -> set[str]:
    """Return the set of POSIX-relative paths already journalled as done.
    
    Postcondition: reads dest / DEDUP_JOURNAL_FILENAME; returns a set of strings.
                   Returns empty set if file absent or unreadable."""

def _write_dedup_journal_entry(fh: IO, rel: str) -> None:
    """Append one POSIX-relative path to the open journal file handle and flush.
    
    Postcondition: rel is appended as a line; fh is flushed (not fsynced per entry;
                   caller fsyncs on close)."""

def run_dedup(
    options: DedupOptions,
) -> DedupMetrics:
    """Top-level dedup orchestration: detect → build plan → review → apply.
    
    Preconditions: options.source and options.dest are valid paths.
    Postconditions:
      - If options.apply_plan_path is set: skip detection; load that plan directly.
      - Else: run detect_duplicates; build_plan; save_plan; save_hash_index.
      - Call review_plan (unless --apply-plan used headlessly).
      - Call apply_plan.
      - Return DedupMetrics with all counts populated.
    Error: SystemExit from review_plan (user quit) propagates; all other errors
           are caught and recorded in metrics."""
```

### Executor Pseudocode

```
apply_plan(plan, options, metrics):
1. Assert plan.source == options.source (raise ValueError if not)
2. done = _load_dedup_journal(options.dest)
3. journal_path = options.dest / DEDUP_JOURNAL_FILENAME
4. fh = open(journal_path, "a", encoding="utf-8")
5. try:
   For each group in plan.groups:
     a. If group.skipped: continue
     b. # Safety: assert keeper is not in removals
        assert group.keeper not in group.removals, f"keeper in removals: {group.keeper}"
     c. For each removal in group.removals:
        rel = removal.relative_to(options.source).as_posix()
        If rel in done: continue  # already processed (resume)
        file_size = 0
        try: file_size = removal.stat().st_size
        except OSError: pass
        If options.dry_run:
            metrics.files_removed += 1
            metrics.bytes_reclaimed += file_size
            _write_dedup_journal_entry(fh, rel)
            done.add(rel)
            continue
        try:
            If not removal.exists():
                # Already gone (idempotent)
                _write_dedup_journal_entry(fh, rel); done.add(rel); continue
            If options.hard_delete:
                removal.unlink()
            Else:
                quarantine_dest = options.dest / DEDUP_BACKUP_DIRNAME / removal.relative_to(options.source)
                quarantine_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(removal), str(quarantine_dest))
            metrics.files_removed += 1
            metrics.bytes_reclaimed += file_size
            _write_dedup_journal_entry(fh, rel)
            done.add(rel)
        except Exception as e:
            metrics.errors.append({"file": str(removal.name), "error": describe_error(e)})
6. finally:
   try: os.fsync(fh.fileno())
   except OSError: pass
   fh.close()
```

### Test Scenarios (U8) — `tests/test_dedup_apply.py`

**T8.1 — quarantine moves removals, keeper intact:**
```python
content = b"ROM" * 512
tree = make_rom_tree(tmp_path / "src", {
    "gba/game.gba": content,
    "gba/backup/game.gba": content,
})
```
Build a plan where keeper=`gba/game.gba`, removal=`gba/backup/game.gba`.
`apply_plan(plan, opts, metrics)`.
Expected: `src/gba/game.gba` still exists; `src/gba/backup/game.gba` does NOT exist;
`dest/dedup_backup/gba/backup/game.gba` exists with same content.

**T8.2 — structure preserved in quarantine:**
Create 3 removals in different subdirectories. Apply plan (quarantine mode).
Expected: all 3 appear under `dest/dedup_backup/` with their relative paths intact.

**T8.3 — dry-run changes nothing:**
Apply plan with `dry_run=True`. Expected: no files moved or deleted; metrics show
`files_removed == len(removals)`; source tree unchanged.

**T8.4 — hard-delete removes files:**
Apply plan with `hard_delete=True`. Expected: removals are gone (not in quarantine);
keeper intact.

**T8.5 — keeper is never touched (invariant):**
Construct a plan where removals accidentally includes the keeper path. Call apply_plan.
Expected: AssertionError raised before any files are touched.

**T8.6 — interrupted apply resumes:**
Create plan with 3 removals. Write journal with 1 removal already done.
`apply_plan(plan, opts, metrics)`. Expected: only the 2 remaining removals are moved;
the already-journalled one is not double-processed.

**T8.7 — failure on one file does not abort batch:**
Make one removal file read-only (or mock shutil.move to raise on first call only).
`apply_plan(plan, opts, metrics)`.
Expected: `metrics.errors` has 1 entry; the other removals are processed.

---

## U9: Dedup Reporting

**Dependencies:** U8.
**Execution wave:** 5 (parallel with U10).
**Files modified:** `rom_stuffer/report.py` (add dedup report functions).
**Files created:** `tests/test_dedup_report.py`.

### Function Signatures and Contracts

```python
# rom_stuffer/report.py (add to existing module)

def generate_dedup_report(
    plan: DedupPlan,
    metrics: DedupMetrics,
    dest_dir: Path,
) -> None:
    """Render dedup results to the console and append to rom_stuffer_report.txt.
    
    Preconditions: plan is the plan that was applied; metrics is from apply_plan;
                   dest_dir is options.dest.
    Postconditions:
      - Console: themed summary panel showing groups_found, files_removed,
          bytes_reclaimed. Labelled 'DRY RUN (estimates)' if metrics.dry_run.
      - Console: keeper→removed table (one row per removal; first column = keeper,
          second = removed path). Capped at CONSOLE_TABLE_ROW_CAP rows.
      - Console: error table if metrics.errors non-empty.
      - File: appends a '--- DEDUP ---' section to dest_dir/'rom_stuffer_report.txt'
          with the same information (uncapped; all entries). All paths formatted
          via str(); no double backslashes (paths are Path objects, not repr'd).
    Error: Rich rendering errors caught and printed as plain text (fallback).
           File write errors caught and printed via console.print (same as compress)."""

def _format_dedup_summary_panel(
    plan: DedupPlan,
    metrics: DedupMetrics,
) -> Panel:
    """Build the themed Rich summary Panel for dedup results.
    
    Postcondition: returns a Panel with a Table.grid of labelled metrics.
                   Border is 'success' if no errors, 'warn' if errors > 0."""

def _format_keeper_table(plan: DedupPlan) -> Table:
    """Build a Rich Table of keeper→removal mappings.
    
    Postcondition: one row per (keeper, removal) pair; keeper in 'success' style;
                   removal in 'muted' style; capped at CONSOLE_TABLE_ROW_CAP rows."""
```

### Test Scenarios (U9) — `tests/test_dedup_report.py`

**T9.1 — report lists each group's keeper and removals:**
Build a plan with 2 groups (2 removals each). Build matching metrics.
`generate_dedup_report(plan, metrics, dest)`.
Expected: `dest / "rom_stuffer_report.txt"` contains "DEDUP" section; contains
both keeper paths and both sets of removal paths.

**T9.2 — dry-run is labelled:**
Set `metrics.dry_run = True`. Call generate_dedup_report.
Expected: report file contains "DRY RUN"; console output (captured) contains "DRY RUN".

**T9.3 — Windows paths no double backslash:**
Create paths with backslash separators by constructing `Path("gba\\game.gba")` on
Windows (or emulate by using string paths). Expected: report shows single-backslash
paths (str(path) gives single backslash; no repr'd paths).

**T9.4 — totals match apply metrics:**
`metrics.files_removed = 3; metrics.bytes_reclaimed = 12 * 1024 * 1024`.
Expected: report contains "3 files" and "12.00 MB" (or formatted equivalent).

**T9.5 — console table caps at CONSOLE_TABLE_ROW_CAP:**
Build a plan with 25 groups (1 removal each; > CONSOLE_TABLE_ROW_CAP=20).
Expected: console output (capture via `rich.console.Console(file=StringIO())`)
shows the cap notice "and N more"; report file contains all 25.

---

## U10: "Both" Flow (Dedup then Compress)

**Dependencies:** U2, U8 (and compress flow from U1).
**Execution wave:** 5 (parallel with U9).
**Files modified:** `rom_stuffer/cli.py` (replace `_run_both` stub).
**Files created:** `tests/test_both_flow.py`.

### Function Signatures and Contracts

```python
# rom_stuffer/cli.py

def _run_both(args: argparse.Namespace) -> None:
    """Run dedup to completion, then compress the surviving files.
    
    Preconditions: args has source, dest (shared); compress args (level, type, etc.);
                   dedup args (keeper_order, protect, etc.).
    Postconditions:
      - Phase 1: run_dedup(options) → apply plan → quarantine/delete duplicates.
      - Phase 2: compress_roms(source, ...) on the now-deduplicated source tree.
      - Combined report: call generate_dedup_report + generate_reports in sequence.
      - dry_run: both phases preview only (no files moved or compressed).
      - The flow is sequential: dedup fully completes (including user review) before
          compress starts. If dedup exits (user quit), compress does not run.
    Error: SystemExit from dedup propagates; compress errors handled by compress_roms."""
```

### Both-Flow Pseudocode

```
_run_both(args):
1. options = DedupOptions(source=..., dest=..., dry_run=args.dry_run, ...)
2. section("De-duplication")
3. metrics_dedup = run_dedup(options)
   # run_dedup internally calls: detect → plan → review → apply → report
4. section("Compression")
5. compress_roms(
       source_dir=args.source,
       file_type=getattr(args, "type", None),
       dest_dir=args.dest,
       sdcard_dir=args.sdcard,
       dry_run=args.dry_run,
       recursive=not getattr(args, "no_recursive", False),
       compress_level=getattr(args, "level", 6),
   )
   # compress_roms calls generate_reports internally
6. # No extra combined report needed; each phase reports itself.
```

### Test Scenarios (U10) — `tests/test_both_flow.py`

**T10.1 — duplicates removed before compression:**
```python
content = b"SNES" * 512
tree = make_rom_tree(tmp_path / "src", {
    "a/game.smc": content,
    "b/game.smc": content,     # duplicate
    "c/unique.smc": b"U" * 512,
})
```
Mock `_run_dedup` to remove `b/game.smc` (simulate quarantine).
`_run_both(args with source, dest, dry_run=False)`.
Expected: `src/a/game.zip` exists; `src/c/unique.zip` exists;
`src/b/` is empty or gone (the duplicate was quarantined); `dest/dedup_backup/` has it.

**T10.2 — survivors all compressed:**
After dedup removes 1 duplicate from a set of 3, the 2 survivors are zipped.
Expected: 2 zip files in source; 1 file in quarantine.

**T10.3 — dry-run previews both stages:**
`dry_run=True`. Expected: no files moved; no zip files created; console shows both
dedup and compress dry-run summaries.

**T10.4 — combined report covers both stages:**
After running both phases, `dest / "rom_stuffer_report.txt"` contains both a DEDUP
section and a COMPRESS section.

---

## U11: Kirby Default + Tetris Theme + Metroid Upgrade

**Dependencies:** U1.
**Execution wave:** 1 (parallel with U2, U3).
**Files modified:** `rom_stuffer/themes.py`.
**Files created:** `tests/test_themes.py`.
**Note:** `assets/` may be updated with banner images; those are out of scope for the
building agent to generate — only the `themes.py` code change is required here.

### New Theme Specifications

All emblems must obey the symmetry rule: no leading or trailing whitespace in any
emblem row outside of Rich markup tags. Each emblem is a multi-line string where
every row produces symmetric visual output when centred.

**Kirby (new default):**
- Palette: pink primary (`#FF78B4`), dark-pink accent (`#D03060`), light body (`#FFB0D0`).
- Semantic mapping: `brand=#FF78B4`, `accent=#D03060`, `info=#FFB0D0`, `success=bold #D03060`,
  `warn=#FFD060`, `danger=bold #E00040`, `muted=dim #A06080`, `value=bold #FF78B4`, `path=#FFB0D0`.
- Border: `#FF78B4`.
- Emblem: original homage pixel-art of a round puffball face (open mouth, blush marks,
  simple eyes). The exact markup string is the builder's creative implementation;
  it must: (a) use only brand/accent/info style tags, (b) be visually centred
  (no leading/trailing spaces outside markup), (c) fit within 12 chars width per row.
- Tagline: "Inhale the duplicates. Stuff more games in."

**Tetris:**
- Palette: primary colour `#00B8D4` (I-piece cyan), `#FFD700` (O-piece gold),
  `#9400D3` (T-piece purple).
- Semantic mapping: `brand=#00B8D4`, `accent=#FFD700`, `info=#C0E0FF`, `success=bold #00D020`,
  `warn=#FFD700`, `danger=bold #E00000`, `muted=dim #6080A0`, `value=bold #FFD700`,
  `path=#00B8D4`.
- Border: `#00B8D4`.
- Emblem: original homage pixel-art of stacked tetromino blocks, a cleared line
  visual, or a falling piece. Same symmetry rule. Max 14 chars wide per row.
- Tagline: "Clear the duplicates. Pack more rows."

**Metroid upgrade:**
- Keep existing `METROID_ART` emblem; improve only if the builder identifies an
  asymmetry. Do not change the colour palette — only fix the art if needed.

### Function Signature Changes

```python
# rom_stuffer/themes.py

DEFAULT_THEME: str = "kirby"   # changed from "zelda" in U1; U11 makes it permanent

THEMES: dict[str, dict]
# Must have exactly four entries after U11: "kirby", "zelda", "metroid", "tetris".
# Each entry schema: same as before (styles dict, art str, label str, tagline str, border str).
# All four must have all 9 semantic style keys.
```

No new function signatures in U11 — the existing `apply_theme`, `print_header`, and
theme infrastructure are unchanged. Only entries are added to `THEMES` and
`DEFAULT_THEME` is updated.

### Test Scenarios (U11) — `tests/test_themes.py`

**T11.1 — all four themes apply without error:**
For name in `["kirby", "zelda", "metroid", "tetris"]`:
`apply_theme(name)`. Expected: no exception; `_active_theme["name"] == name`.

**T11.2 — default is kirby:**
`apply_theme("nonexistent_theme")`. Expected: `_active_theme["name"] == "kirby"`.

**T11.3 — unknown theme falls back to default:**
`apply_theme("whatevs")`. Expected: `_active_theme["name"] == "kirby"`.

**T11.4 — every semantic style resolves for every theme:**
For each theme: `apply_theme(name)`; render `"[brand]test[/brand]"` via
`console.render_str(...)`. Expected: no `rich.errors.StyleSyntaxError`.

**T11.5 — emblems are symmetric (no leading/trailing whitespace outside markup):**
For each theme's art string: split on `\n`; for each line, strip Rich markup tags
(`re.sub(r"\[.*?\]", "", line)`); assert the result has no leading or trailing spaces.

**T11.6 — --theme flag sets correct theme:**
Mock argv with `["rom_stuffer.py", "compress", "--theme", "tetris", "-s", "...", "-d", "..."]`.
Call `main()` (with compress_roms mocked). Expected: `_active_theme["name"] == "tetris"`.

---

## Appendix A: Hash Index JSON Schema

**File name:** `.rom_stuffer_hash_index.json`
**Location:** `<dest>` directory (the backup/destination root).
**Written by:** `save_hash_index()` in `rom_stuffer/planfile.py`.
**Read by:** Phase 2 per-system space estimator (future); `load_hash_index()`.

### Schema

```json
{
  "version": 1,
  "created_at": "<ISO-8601 UTC timestamp>",
  "source": "<absolute path to scan root>",
  "records": [
    {
      "path": "<POSIX relative path from source root>",
      "sha256": "<64-char lowercase hex SHA-256 of logical content>",
      "logical_size": "<int: uncompressed bytes>",
      "stored_size": "<int: on-disk bytes>"
    }
  ]
}
```

**Key properties:**
- `logical_size` == `stored_size` for raw (uncompressed) files.
- `logical_size` > `stored_size` (typically) for zip files.
- Records with the same `sha256` are byte-identical duplicates.
- Records where `sha256` is `""` were enumerated but not content-hashed (size singletons).
- `path` uses forward-slash separators on all platforms (`.as_posix()`).

### Concrete Example

```json
{
  "version": 1,
  "created_at": "2026-07-17T14:22:31Z",
  "source": "/Users/player1/roms",
  "records": [
    {
      "path": "gba/Metroid Fusion (USA).gba",
      "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "logical_size": 8388608,
      "stored_size": 8388608
    },
    {
      "path": "gba/backup/Metroid Fusion (USA).gba",
      "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "logical_size": 8388608,
      "stored_size": 8388608
    },
    {
      "path": "gba/Metroid Fusion (USA).zip",
      "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "logical_size": 8388608,
      "stored_size": 5200000
    },
    {
      "path": "nes/Mega Man (USA).nes",
      "sha256": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
      "logical_size": 131072,
      "stored_size": 131072
    }
  ]
}
```

Notes on the example: the first three records share the same `sha256` — one raw file,
one raw backup, one zip — all containing identical ROM content. `logical_size` is 8 MB
for all three (the uncompressed game). `stored_size` of the zip is ~5 MB (DEFLATE).

---

## Appendix B: Dedup Plan File Format

**File name:** `.rom_stuffer_dedup_plan.txt`
**Location:** `<dest>` directory.
**Written by:** `save_plan()` in `rom_stuffer/planfile.py`.
**Read by:** `load_plan()`; may also be opened and edited by the user.

### Format

Plain UTF-8 text. Lines starting with `#` are comments. Groups are delimited by
`--- GROUP N/M ---` headers. A group marked `# SKIP` (on the line immediately
preceding its header) is ignored by the executor.

### Edit Rules for Users

1. To change which copy is kept: swap the `KEEP:` path with a `REMOVE:` path.
   Move the former `KEEP:` path to a `REMOVE:` line and promote the desired `REMOVE:`
   to `KEEP:   ` (note: three spaces after the colon are canonical but the parser
   accepts any whitespace).
2. To skip a group entirely: add `# SKIP` on its own line directly before the
   `--- GROUP N/M ---` line.
3. Do not change sha256 lines (they are for audit only; the executor uses path lines).
4. Do not add or remove groups; only edit KEEP/REMOVE within a group or add `# SKIP`.

### Parse Rules (implemented in `load_plan`)

- Header section: lines before the first `--- GROUP` that match `# key: value` pattern
  are parsed as metadata. Required keys: `version`, `source`, `created`.
- `# SKIP` (any capitalisation, any surrounding whitespace after stripping) on the
  line immediately before a `--- GROUP` line marks that group as skipped.
- `KEEP:` line: everything after `KEEP:` stripped of whitespace is the keeper path
  (POSIX relative to source).
- `REMOVE:` line: everything after `REMOVE:` stripped of whitespace is a removal path.
- `sha256:` and `reclaims:` lines are informational; `sha256` is stored; `reclaims` is
  ignored (recalculated).
- Blank lines are ignored.
- The parser must tolerate extra `#` comment lines inside groups.

### Concrete Example

```
# ROM Stuffer Dedup Plan
# version: 1
# source: /Users/player1/roms
# created: 2026-07-17T14:22:31Z
# Edit this file: change KEEP/REMOVE lines, or add '# SKIP' before a group header.

--- GROUP 1/3 ---
sha256: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
reclaims: 16.00 MB
KEEP:   gba/Metroid Fusion (USA).gba
REMOVE: gba/backup/Metroid Fusion (USA).gba
REMOVE: gba/Metroid Fusion (USA).zip

# SKIP
--- GROUP 2/3 ---
sha256: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
reclaims: 128.00 KB
KEEP:   nes/Mega Man (USA).nes
REMOVE: nes/dupes/Mega Man (USA).nes

--- GROUP 3/3 ---
sha256: cafef00dcafef00dcafef00dcafef00dcafef00dcafef00dcafef00dcafef00d
reclaims: 4.00 MB
KEEP:   snes/Super Mario World (USA).smc
REMOVE: snes/copies/Super Mario World (USA).smc

```

In this example: GROUP 1 will quarantine two removals. GROUP 2 has `# SKIP` so the
executor ignores it entirely. GROUP 3 will quarantine one removal.

---

## Appendix C: CLI Subcommand Spec

This is the exact argparse structure. `_build_parser()` must produce a parser matching
this spec. Short forms listed first; long forms required; types and defaults explicit.

### Shared Parent Parser (add_help=False, used as parents=[parent])

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-s`, `--source` | str | None | Source directory |
| `-d`, `--dest` | str | None | Destination/backup directory |
| `-sd`, `--sdcard` | str | None | SD card target directory |
| `--dry-run` | flag (store_true) | False | Preview only, no file changes |
| `--theme` | str, choices=sorted(THEMES) | None | Visual theme name |
| `--resume` | flag (store_true) | False | Resume an interrupted job |
| `--fresh` | flag (store_true) | False | Discard saved state and rescan |

### `compress` Subcommand

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-t`, `--type` | str | None | Target extension (e.g. `.gba`) |
| `--no-recursive` | flag (store_true) | False | Disable sub-folder scan |
| `-l`, `--level` | int, choices=1-9 | 6 | DEFLATE level |

### `dedup` Subcommand

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--keeper-order` | str | None | Comma-separated folder priority list |
| `--protect` | str (appendable) | [] | Never-remove folder (repeatable) |
| `--per-system` | flag (store_true) | False | Only dedup within same system folder |
| `--min-size` | int | 0 | Skip files smaller than N bytes |
| `--interactive` | flag (store_true) | False | Per-group confirmation in TUI |
| `--hard-delete` | flag (store_true) | False | Delete instead of quarantine |
| `--apply-plan` | str (Path) | None | Path to a saved plan file to apply |

### No-Arg Interactive Menu

When `sys.argv` has only the program name (no subcommand, no flags):
```
What would you like to do?

  [1]  Compress ROMs
  [2]  Find duplicates
  [3]  Both  (de-duplicate first, then compress)

Enter choice [1/2/3]:
```
After choice, prompt for source and dest (and optionally sdcard, dry-run) in the same
style as the existing interactive prompts. Route to `_run_compress`, `_run_dedup`,
or `_run_both`.

### Precedence and Routing

```
main():
    if len(sys.argv) == 1:
        _interactive_menu()
        return
    args = _build_parser().parse_args()
    if args.theme:
        apply_theme(args.theme)
    else:
        apply_theme(DEFAULT_THEME)
    print_header()
    if args.subcommand == "compress":
        _run_compress(args)
    elif args.subcommand == "dedup":
        _run_dedup(args)
    else:
        # Should not reach here (argparse enforces subcommand)
        _build_parser().print_help()
        sys.exit(1)
```

Note: `Both` is menu-only in Phase 1 (no `both` subcommand). The `_run_both` function
is accessible via menu choice 3 only.

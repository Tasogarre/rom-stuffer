# Code Review: `compress_roms.py`

Scope: performance, correctness/race conditions, functional edge cases, and general
quality. Reviewed against the current working tree. Findings are ranked by severity;
each carries a `file:line` anchor and a suggested fix block.

A parallel-agent review produced the raw findings; every load-bearing item below was
independently verified against the source before inclusion. Verified **non-issues**
are listed at the end so they aren't re-investigated.

---

## P1 — Critical (data loss or batch-aborting crashes)

### 1. `original_size` is unbound/stale outside the `try` → crash or corrupted progress
`compress_roms.py:100` (assignment) vs `compress_roms.py:142` (use).

`original_size` is bound at line 100 *inside* the `try`, but line 142
(`progress.advance(byte_task, advance=original_size)`) runs unconditionally after the
`except`. If `file_path.stat()` (line 100) or `relative_to` (line 96) raises — file
removed after the scan, permission loss, over-long path — then on the **first** file
`original_size` is unbound → uncaught `NameError` that aborts the entire batch and
skips `generate_reports`; on a **later** file it silently advances the byte bar by the
*previous* file's size.

```python
for file_path in files_to_process:
    original_size = 0
    try:
        ...
        original_size = file_path.stat().st_size
        ...
    except Exception as e:
        metrics.error_count += 1
        metrics.errors.append({'file': str(file_path.name), 'error': str(e)})
    finally:
        progress.update(overall_task, description=f"[cyan]Processed {escape(file_path.name)}...")
        progress.advance(overall_task)
        progress.advance(byte_task, advance=original_size)
```

### 2. `.zip` target collision silently destroys a ROM in the playable library
`compress_roms.py:98` (`zip_path = file_path.with_suffix('.zip')`), written at `:104`.

Two supported files sharing a stem but differing in extension — very common:
`Game.gb` + `Game.gbc`, `Game.nes` + `Game.gb`, `Game.bin` + `Game.md` — both map to
`Game.zip`. Whichever is processed second overwrites the first's archive (and the SD
copy at `:123`). Originals survive in `dest`, but the library now contains only one of
the two games, with no warning. A pre-existing unrelated `Game.zip` is likewise
overwritten.

**Recommended fix (per the requested scheme): default to `filename.zip`; on a clash,
fall back to `filename_ext.zip`.** This keeps the clean name RetroArch/scrapers expect
in the common case and only disambiguates when needed. It also closes finding #3.

```python
def build_zip_path(file_path: Path) -> Path:
    """Game.zip normally; Game_gb.zip / Game_gbc.zip when the name is already taken."""
    default = file_path.with_suffix('.zip')
    # Clash if the target already exists OR would equal the source (e.g. -t zip).
    if default != file_path and not default.exists():
        return default
    disambiguated = file_path.parent / f"{file_path.stem}_{file_path.suffix.lstrip('.')}.zip"
    # Guard the rare case where the disambiguated name is also taken.
    counter = 1
    candidate = disambiguated
    while candidate.exists() and candidate != file_path:
        candidate = file_path.parent / f"{file_path.stem}_{file_path.suffix.lstrip('.')}_{counter}.zip"
        counter += 1
    return candidate
```
The internal entry name stays the true ROM filename (`zipf.write(file_path, file_path.name)`
at `:105`), so emulators still load it correctly.

### 3. `-t zip` (or a source file already ending `.zip`) truncates the original
`compress_roms.py:98` + `:104`. The `--type` branch (`:278-298`) never validates
`file_type` against `SUPPORTED_EXTENSIONS`, so `python compress_roms.py -s ... -t zip -d ...`
reaches `with_suffix('.zip')`, which for `Game.zip` returns the **same path**; line 104
then opens it `'w'` and truncates the ROM to zero bytes before line 105 tries to add the
now-empty file to itself. Irreversible data loss.

Fixed by `build_zip_path` above (the `default != file_path` guard). Additionally reject
unknown target types up front:
```python
if file_type and file_type.lower() not in SUPPORTED_EXTENSIONS:
    console.print(f"[bold red]Refusing to process unsupported/unsafe type '{file_type}'.[/bold red]")
    sys.exit(1)
```

### 4. Rich markup injection from bracketed ROM filenames crashes the batch
`compress_roms.py:113`, `:140` (also `:311`). Filenames are interpolated straight into
Rich markup strings. Standard No-Intro/GoodTools tags — `Zelda (U) [!].gb`,
`Sonic [T+Eng1.0].md`, `[b1]` — make Rich parse `[...]` as a style tag and raise
`MarkupError`/`StyleSyntaxError`. Line 140 is **outside** the per-file `try`, so such a
name crashes the whole batch rather than being recorded.

```python
from rich.markup import escape
# every place a filename is shown:
progress.update(overall_task, description=f"[magenta]Syncing {escape(file_path.name)} to SD...[/magenta]")
...
metrics.skipped_files.append({'file': escape(str(p.name)), 'reason': ...})
```

---

## P2 — High (partial/half-applied operations, aborts, misleading output)

### 5. Upfront `sum(f.stat().st_size ...)` outside any `try` aborts the entire run
`compress_roms.py:92`. Eagerly stats every file to size the progress bar, before the
per-file `try`. A single unreadable/removed file, permission error, or over-long path
throws here and aborts the whole run before one ROM is processed — even though the scan
loop (`:288`, `:312`) carefully catches `OSError`. (Also a perf issue — see #12.)

```python
total_bytes = 0
for f in files_to_process:
    try:
        total_bytes += f.stat().st_size
    except OSError:
        pass
byte_task = progress.add_task("[green]Data processed...", total=total_bytes)
```

### 6. SD delete-before-copy is intentional (space-constrained cards) — harden, don't reverse
`compress_roms.py:119-123`. `sd_equivalent_original.unlink()` runs, then
`fast_sd_copy`. **This ordering is required**: on a nearly-full SD card there isn't room
to hold both the old uncompressed original and the new `.zip` at once, so the old file
*must* be deleted first to free space. Do **not** reverse it to copy-then-delete.

It is also acceptably safe as-is: by this point the freshly-built `.zip` already exists in
the **source** directory (written at `:104`) and the source original isn't moved out until
`:128`, so the authoritative copy is never on the SD card alone. If `fast_sd_copy` throws,
the SD loses only its copy of that one title, which a re-run reproduces from the zip still
sitting in source.

The improvement is therefore *robustness and control*, not reordering:
- Keep delete-first, but make it explicit and toggleable (e.g. `--sd-delete-first` /
  `--sd-keep-original`, defaulting to delete-first for this tool's space-constrained
  target).
- On copy failure, report it clearly per-file and continue, so a mid-write card removal is
  visible rather than a silent gap.
- Use `unlink(missing_ok=True)` (finding #18) to drop the extra `exists()` stat.

```python
# Space-constrained SD: free the slot first, then write the new zip.
sd_equivalent_original.unlink(missing_ok=True)
try:
    fast_sd_copy(zip_path, sd_equivalent_zip)
    metrics.sd_files_synced += 1
    metrics.sd_bytes_copied += zip_size
except OSError as e:
    metrics.errors.append({'file': str(file_path.name), 'error': f"SD copy failed: {e}"})
    # zip remains in source; a re-run restores the SD copy.
```

### 7. Partial/corrupt `.zip` left behind if compression fails mid-write
`compress_roms.py:104-105`. `ZipFile(zip_path, 'w')` truncates immediately; a failure
during `zipf.write` (disk full, read error) leaves a truncated `.zip` at the target.
Write to a temp file and atomically rename on success:
```python
tmp = zip_path.with_name(zip_path.name + '.tmp')
with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=level) as zipf:
    zipf.write(file_path, file_path.name)
tmp.replace(zip_path)
```

### 8. `shutil.move` failure leaves duplicate state; SD metrics counted too early
`compress_roms.py:124-125` (SD counters) vs `:128` (move). SD counters increment before
the move. A read-only source file or cross-device failure on the move throws: the source
now holds *both* the original and the new `.zip`, `success_count` was never incremented,
yet `sd_files_synced` already counted it. Move first (or clean up the created zip on
move failure), and increment SD metrics only after the operation is durable.

### 9. Broad `except Exception` hides these partial states; no `fsync` durability
`compress_roms.py:136`; `fast_sd_copy` at `:70-78`. Catch narrower exceptions
(`OSError`, `zipfile.BadZipFile`), clean up a partial `zip_path` in a `finally`, and
flush to disk so "synced" means durable — important for removable media:
```python
def fast_sd_copy(source_path: Path, dest_path: Path, buffer_size: int = 4 * 1024 * 1024) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(source_path, 'rb') as fsrc, open(dest_path, 'wb') as fdst:
        shutil.copyfileobj(fsrc, fdst, length=buffer_size)
        fdst.flush()
        os.fsync(fdst.fileno())
```

### 10. No validation that `dest` differs from / is outside `source`
`compress_roms.py:244-254`. If `dest == source`, `original_dest` equals `file_path` and
`shutil.move` moves a file onto itself while a zip is written into the scanned tree. If
`dest` (or `sdcard`) is *inside* `source`, a later run rescans the backups.
```python
if dest_path == source_path or source_path in dest_path.parents or dest_path in source_path.parents:
    console.print("[bold red]Error: destination must differ from and not overlap the source.[/bold red]")
    sys.exit(1)
```

### 11. Dry-run report file is not labelled as an estimate
`compress_roms.py:203-218`. The console summary title gets a `(DRY RUN)` suffix
(`:152-153`), but the written `rom_stuffer_report.txt` has no marker and reports the
`int(original_size * 0.4)` estimate (`:109`) as if it were measured. Add a `DRY RUN`
banner to the file header and label size rows "(estimated)" when `metrics.dry_run`.

---

## P3 — Medium / low (performance & quality)

12. **Triple-stat per file.** `:92`, `:100`, and `is_file()` at `:286`/`:307` each stat
    the same file; on slow SD/USB paths that's 3 syscalls where 1 would do. Capture size
    once during scan and carry `(path, size)` pairs into `compress_batch`.

13. **DEFLATE level not tuned.** `:104` uses zlib's default level 6 — CPU-heavy and the
    dominant cost on the low-end devices this tool targets. Expose a `--level` and pass
    `compresslevel=` (default 1-3); ROM data barely shrinks further past level 3.

14. **16MB copy buffer over-allocates; docstring claim is false.** `:70-78`.
    `copyfileobj` allocates up to `length` bytes per read, spiking ~16MB heap per copy for
    files usually far smaller, and the buffer does **not** "avoid OS caching overhead"
    (no `O_DIRECT`). Drop to 1-4MB (folded into #9's fix).

15. **`--type` mode is case-sensitive on Linux/macOS.** `:283` `rglob(f"*{file_type}")`
    misses `.GB`/`.SFC`, while interactive mode lowercases via `p.suffix.lower()` (`:308`).
    Normalize case for parity (e.g. match on `p.suffix.lower() == file_type.lower()`).

16. **No type hints on any function** (`:60`, `:70`, `:80`, `:144`, `:244`). e.g.
    `def compress_roms(source_dir: str, file_type: str | None, dest_dir: str, sdcard_dir: str | None = None, dry_run: bool = False, recursive: bool = True) -> None:`

17. **Inconsistent prompt style.** `:270` uses bare `input()` for the SD path while every
    other prompt uses `Prompt.ask`/`Confirm.ask`. Replace with `Prompt.ask(...)`.

18. **`unlink(missing_ok=True)` removes an extra stat.** `:119` does `exists()` then
    `unlink()`; `sd_equivalent_original.unlink(missing_ok=True)` is one syscall (Py 3.8+).

19. **Console error table is unbounded** while the skipped table caps at 20 (`:178-181`
    vs `:189-190`); a large failure run floods the terminal. Cap the console error table
    too — the full list is already in the log file.

20. **Magic numbers / no `logging`.** `0.4` (`:109`), `16 * 1024 * 1024` (`:70`), `20`
    (`:178`), `5` (`:325`). Extract named constants; consider the `logging` module for
    level-controlled diagnostics separate from the Rich report.

21. **`SUPPORTED_EXTENSIONS` — add a trailing comma after `'.o2'`** (`:39`). Not currently
    a bug, but without it a future appended string would silently concatenate
    (`'.o2''.new'` → one element). Cheap insurance.

---

## Verified non-issues (checked; no action needed)

- **`rglob("*.gb")` does not over-match `.gbc`** — `fnmatch` anchors the pattern at the
  end, so `mario.gb` matches but `mario.gbc` does not (`:283`).
- **No integer overflow** — Python ints are arbitrary-precision; `int(original_size * 0.4)`
  and `st_size` are fine at multi-GB (`:109`).
- **Unicode is handled** — the report opens with `encoding='utf-8'` (`:205`) and zip entry
  names use the UTF-8 flag (`:105`).
- **Newly created zips are not re-scanned mid-run** — both scan paths fully materialize the
  file list before processing, and `.zip` isn't in `SUPPORTED_EXTENSIONS`.
- **Report-write failure is not silent** — caught and reported (`:241-242`).
- **Empty source, zero-byte files, broken symlinks, and Windows `F:\` roots** are all
  handled (`:291-293`, `:264`, `p.is_file()` excludes broken symlinks).

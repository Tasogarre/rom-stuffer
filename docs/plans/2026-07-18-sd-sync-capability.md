---
title: SD-card sync as a first-class capability (sync command + all pipeline + TUI)
date: 2026-07-18
status: done
base_ref: main
---

# SD-card sync capability

## Goal
Make "push local library → SD card" a first-class, independent-yet-chainable
capability alongside `compress` and `dedup`. TUI is the primary surface.

## Decided design (user-confirmed)
- **Full-mirror-prune by default**: `sync` deletes card files with no local
  counterpart. Safety rails: `--dry-run` preview, explicit confirm before any
  prune in interactive/TUI, **refuse to prune when the source scan is empty**
  (guards against wiping the card on a wrong path), `--no-prune` escape hatch.
- **Three surfaces**: per-command `-sd`; a new `sync` subcommand; an `all`
  pipeline (dedup → compress → sync). **All must appear in the no-arg TUI menu.**
- Sequential writes only (flash-media constraint) — reuse `fast_sd_copy`.

## Units & ownership (disjoint per wave)

### Wave 1 (parallel worktree writers)

**Unit 1 — Sync engine.** Owns: `rom_stuffer/sync.py` (new), `tests/test_sync.py` (new).
- `SyncOptions(source, sdcard, dry_run=False, prune=True, recursive=True)`
- `SyncMetrics(files_copied, bytes_copied, files_skipped, files_pruned, bytes_pruned, errors, dry_run, prune_blocked_empty_source)`
- `mirror_to_sdcard(options, progress_callback=None) -> SyncMetrics`: walk source; copy file to `sdcard/rel` when missing or size differs (via `fast_sd_copy` from `rom_stuffer.compress`), else skip; if `prune`, delete card files whose rel path is not in source; **if source set is empty, set `prune_blocked_empty_source=True` and prune nothing**; dry-run counts only.
- `render_sync_report(metrics, sdcard, console=None)` — self-contained Rich output (do NOT edit report.py).
- `run_sync(args) -> SyncMetrics` — reads args.source/sdcard/dry_run, prune from `not args.no_prune`, recursive from `not args.no_recursive`.
- Tests: copy-new, skip-identical, copy-on-size-change, prune-deletes-extras, no-prune-keeps-extras, dry-run-touches-nothing, empty-source-safety, subdir-structure-preserved.

**Unit 2 — Dedup SD-awareness.** Owns: `rom_stuffer/dedup.py`, `rom_stuffer/report.py`, `tests/test_dedup_apply.py`.
- Add `sdcard: Path | None = None` to `DedupOptions`.
- In `apply_plan`, when a removal is quarantined/hard-deleted and `options.sdcard` is set (and not dry-run), also delete its card counterpart `sdcard / removal.relative_to(source)` if present; count `sd_files_pruned`/`sd_bytes_pruned`. Keeper's card copy is NEVER removed.
- Add `sd_files_pruned=0`, `sd_bytes_pruned=0` to `DedupMetrics`.
- `run_dedup` threads `args.sdcard` (absent → None) onto `DedupOptions`.
- `report.py generate_dedup_report`: show SD prune line when `sd_files_pruned > 0`.
- Tests: card counterpart removed on apply; dry-run leaves card untouched; hard-delete+sdcard removes card copy; keeper card copy preserved.

### Wave 2 (parent-owned integration — depends on 1 & 2)

**Unit 3 — CLI + TUI wiring.** `rom_stuffer/cli.py`, `tests/test_cli.py`.
- `sync` subparser (parent flags + `--no-prune`, `--no-recursive`); `_run_sync`.
- `all` subparser (compress+dedup flags); `_run_all` = dedup(local) → compress(local) → sync-mirror(-sd) with a final full mirror.
- Redesign `_interactive_menu`: actions 1 Compress / 2 Find duplicates / 3 Sync to SD / 4 Everything; prompt for SD-card path where relevant; confirm before a destructive prune.

**Unit 4 — Docs.** `README.md` (+ CLAUDE.md architecture note): new Sync section, `all`, TUI updates.

## Verification
- Full `pytest` green.
- Independent end-to-end synthetic test: fake library + fake SD dir → run mirror → assert copied, pruned, structure preserved, and empty-source safety refuses to prune.

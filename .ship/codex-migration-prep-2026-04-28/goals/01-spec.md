# SPEC — Codex Migration Prep Package (2026-04-28)

Reverse-engineered from the artifact set produced by strict-execute on 2026-04-28 to
`~/Desktop/Codex_Migration_Prep_2026-04-28/`. Authoritative if Codex (downstream consumer)
wants to know "what was promised vs what shipped".

## §1 Goal

Produce a **read-only** inventory + cross-host dependency map of every Claude Code
hook on Bernard's Mac so that Codex (a different AI harness) can take a deterministic
position on each one: **port-direct / port-with-effort / claude-only / external-git-hook /
drop-redundant**. No migration execution, no settings.json edits, no hook deletions in this
phase.

## §2 Hard constraints (READ-ONLY)

- C1. No writes to `~/.claude/settings.json` (or `settings.local.json`). Verified post-run via mtime.
- C2. No writes to any file under `~/.claude/hooks/`, `~/telegram-claude-bot/{hooks,claude_hooks}/`, `~/claude-skills-curation/hooks/`.
- C3. No writes on Hel or London (only `ssh <host> "<read-only cmd>"` allowed).
- C4. `_inventory-script.py` is non-destructive (reads + emits CSV to Desktop only).
- C5. Recommended deletions are **listed only**, never executed.

## §3 Deliverables (5 files, all under `~/Desktop/Codex_Migration_Prep_2026-04-28/`)

| # | File | Purpose | Key shape |
|---|---|---|---|
| 1 | `_inventory-script.py` | Generator script for D2 | Python, stdlib-only, ≤300 lines |
| 2 | `hook-surface-inventory.csv` | Row-per-(hook, event) inventory | 19-col schema; 1 header + ≥334 data rows |
| 3 | `active-hook-runtime-map.md` | Per-event breakdown of `settings.json` wired hooks | 11 event sections; entry counts + unique-file counts |
| 4 | `hook-hard-block-audit.md` | Active hard-blockers, 30d hit counts, deploy-window caveat, bypass log | 14 active + 33 inactive; caveat at TOP |
| 5 | `hook-file-dedupe-report.md` | 4-source-tree dedupe with classifications + recommended-deletions list | 4 tables; LISTING ONLY |
| 6 | `hel-london-hook-dependency-map.md` | Hooks/scripts that reach Hel or London via ssh | live-verified Hel + London + 8 active hook deps |

(D6 was added in execute-phase as part of the 5-file scope; net 5 markdown + 1 CSV + 1 script = 6 artifacts.)

## §4 CSV schema (19 columns, fixed order)

`hook_file, event, matcher, active_in_settings, command, source_tree, mirror_status,
hook_family, decision_power, side_effects, reads, writes, external_deps, host_scope,
sharing_model, codex_target, port_priority, evidence_needed, notes`

- `decision_power ∈ {hard-block, soft-warn, mutate, info}`. No `unknown` values allowed in final CSV.
- `hook_family` = 4-class taxonomy (dispatcher / guard / tracker / other).
- `source_tree ∈ {claude-hooks, tcb-hooks, tcb-claude_hooks, curation-hooks}`.
- `active_in_settings ∈ {true, false}`. Reconciles to `settings.json` parse.
- `codex_target ∈ {port-direct, port-with-effort, claude-only, external-git-hook, drop-redundant}`.
- `port_priority ∈ {P0, P1, P2, P3}`.

## §5 Coverage targets

- C-S1. CSV must include every file under the 4 source trees:
  - `~/.claude/hooks/` ............... 139 files (spec count)
  - `~/telegram-claude-bot/hooks/` ... 123 files
  - `~/telegram-claude-bot/claude_hooks/` 72 files
  - `~/claude-skills-curation/hooks/` 0 files (per spec)
- C-S2. Every event in `settings.json.hooks` keyed: PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart, SessionEnd, PreCompact, TaskCompleted, SubagentStart, SubagentStop, PermissionRequest (11 events).
- C-S3. `active_in_settings=true` row count must reconcile to settings.json parse (entry-level fan-out by matcher allowed; explain delta in doc).

## §6 Verification gates per artifact

- V-D2 (CSV): parse cleanly with python `csv` module; every row has 19 fields; `decision_power` in enum.
- V-D3 (runtime map): per-event tables cite `settings.json:<line-range>` for each block.
- V-D4 (hard-block audit): **deploy-window caveat at TOP** with "lower bounds, not steady-state" wording. Each row: file:line citation for block mechanism. Bypass log present.
- V-D5 (dedupe): 4 tables, recommended deletions = subset of `classification ∈ {stale-dead, backup}`. "LISTING ONLY — DO NOT DELETE" prefix.
- V-D6 (Hel/London map): Bot-liveness 3-step protocol verbatim outputs embedded with `[verified-live <ISO-ts>]` tag. SSH alias usage map. Risk priorities ranked.

## §7 Citation discipline (from CLAUDE.md §Epistemic discipline)

- Every load-bearing claim in `.md` files carries `[cited file:line]` / `[cited cmd]` / `[GAP — unverified, exp:<X>]`.
- Citations ≤5 lines, cited line contains the keyword/symbol/value claimed.
- Bot-liveness assertions follow 3-step protocol (`systemctl is-active` + `journalctl --since 5min ago` + `systemctl show -p MainPID`).
- File mtime alone is NOT evidence of liveness (CLAUDE.md §Mtime-trap).

## §8 Out of scope (explicit)

- O-1. No execution of recommended deletions in this phase.
- O-2. No edits to `settings.json` to disable inactive hooks.
- O-3. No writes to Hel/London (read-only ssh inventory only).
- O-4. No port to Codex format — that is the next phase. This phase only produces inputs.
- O-5. No tcb-hooks/ + tcb-claude_hooks/ classification beyond mirror-of-claude-hooks vs unique. Detailed per-file verdicts deferred.

## §9 Done definition

Phase closes when (a) all 6 artifacts non-empty and at expected line counts, (b) CSV passes V-D2, (c) deploy-window caveat present per V-D4, (d) Hel/London 3-step verifier output embedded per V-D6, (e) no `~/.claude/settings.json` mtime advance during run.

#!/usr/bin/env python3
# Hook: SKILL-mode /ship Phase 4 LAND requires route-trace.md
# Created: 2026-04-29
# Trigger: PreToolUse Bash. When command is a finalization verb
# (git commit/push, cp/mv into ~/.claude/skills, install symlink, ln -s)
# AND a .ship/<slug>/ slug exists in cwd or recent context AND that slug
# touches a skill subdir, require .ship/<slug>/experiments/route-trace.md
# to exist and be ≥30 lines (route trace is non-trivial).
#
# Source: combo/skill-route-trace-gate
# Rule: rules/ship.md §SKILL-mode route-trace gate
import json
import os
import pathlib
import re
import sys


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = (data.get("tool_input") or {}).get("command", "") or ""

    # Finalization verbs that close a /ship phase
    finalization_pat = re.compile(
        r"\b(git\s+(commit|push)|"
        r"cp\s+.*~/?\.claude/skills|"
        r"mv\s+.*~/?\.claude/skills|"
        r"ln\s+-s.*~/?\.claude/skills|"
        r"install\s+-d.*~/?\.claude/skills)\b"
    )
    if not finalization_pat.search(cmd):
        sys.exit(0)

    # Heuristic: did this command touch a skill at all?
    skill_pat = re.compile(r"~/?\.claude/skills/([\w-]+)")
    skill_match = skill_pat.search(cmd)

    # Search recent .ship/<slug> dirs (last 24h) under ~ and look for ones
    # whose changeset touches a skill subdir.
    home = pathlib.Path(os.path.expanduser("~"))
    ship_root = home / ".ship"
    if not ship_root.exists():
        sys.exit(0)

    candidates = []
    for slug_dir in ship_root.iterdir():
        if not slug_dir.is_dir():
            continue
        spec = slug_dir / "goals" / "01-spec.md"
        if not spec.exists():
            continue
        # skim spec for SKILL keywords
        try:
            head = spec.read_text(errors="ignore")[:4000].lower()
        except Exception:
            continue
        if "skill" not in head and "/skills/" not in head:
            continue
        # skim 04-land-skill.md or 04-land.md
        land_paths = [
            slug_dir / "04-land-skill.md",
            slug_dir / "04-land.md",
        ]
        if not any(p.exists() for p in land_paths):
            continue
        candidates.append(slug_dir)

    if not candidates:
        # No active SKILL ship — but the command still touched a skill.
        # Soft-fail with informational message only when skill_match is set.
        if skill_match:
            print(
                json.dumps(
                    {
                        "decision": "continue",
                        "outputMessage": (
                            "[skill_route_trace_gate] command touches "
                            f"~/.claude/skills/{skill_match.group(1)} but no "
                            "active .ship/<slug>/ found — skipping route-trace "
                            "check. If this was a SKILL /ship, set up "
                            ".ship/<slug>/experiments/route-trace.md before "
                            "finalizing per rules/ship.md §SKILL-mode "
                            "route-trace gate."
                        ),
                    }
                )
            )
        sys.exit(0)

    # For each active SKILL ship, require route-trace.md ≥30 lines.
    blockers = []
    for slug_dir in candidates:
        trace = slug_dir / "experiments" / "route-trace.md"
        if not trace.exists():
            blockers.append(
                f"missing: {trace} — SKILL ship {slug_dir.name} has no "
                f"route-trace yet. See rules/ship.md §SKILL-mode route-trace "
                f"gate for required content (representative prompt, file:line "
                f"citations per axis, expected emit)."
            )
            continue
        try:
            line_count = sum(1 for _ in trace.read_text(errors="ignore").splitlines())
        except Exception:
            line_count = 0
        if line_count < 30:
            blockers.append(
                f"too thin: {trace} ({line_count} lines, need ≥30) — route "
                f"trace must cover ≥3 router axes with file:line citations."
            )

    if blockers:
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "SKILL-mode route-trace gate: cannot finalize.\n  "
                        + "\n  ".join(blockers)
                        + "\n\nFix: write the route-trace per rules/ship.md "
                          "§SKILL-mode route-trace gate, then retry. To bypass "
                          "intentionally (e.g. trace already verified out-of-band), "
                          "include `[skip-route-trace=<reason>]` in the commit "
                          "message subject."
                    ),
                }
            )
        )
        sys.exit(0)

    # All checks passed.
    sys.exit(0)


if __name__ == "__main__":
    main()

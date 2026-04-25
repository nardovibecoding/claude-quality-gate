#!/usr/bin/env python3
"""
approval_executor.py — Big SystemD Phase 8-3 + FP-4 (slices 3a/3b/3c)

Reads ~/inbox/_approvals/*.json, looks up the corresponding archived brief,
maps the approved action to a WHITELISTED action type, runs V1-V5 gates,
applies the action, and writes an audit log entry.

Allowlisted action types (NO free-text shell_exec -- ever):
  file_delete       -- delete a single file (no glob, path-bounded)
  file_edit         -- apply a unified diff to a file
  systemd_reload    -- launchctl kickstart/bootout for bigd- plists on mac
  plist_reload      -- unload+load a com.bernard.bigd-* plist
  launchd_enable    -- launchctl load a plist
  launchd_disable   -- launchctl unload a plist
  inbox_archive     -- move a finding from inbox to archive (no-op action)
  no_op             -- defer/skip -- write audit record, take no action

Usage:
  python3 ~/.claude/hooks/approval_executor.py [--dry-run]
  python3 ~/.claude/hooks/approval_executor.py --rollback <exec_id>

Audit log: ~/inbox/_audit/executor_<YYYYMMDD>.jsonl
Rollback files: ~/inbox/_rollback/<exec_id>/
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Shared audit rotation helper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _audit_rotation import rotate_audit_files as _rotate_audit_files
    _SHARED_ROTATION = True
except ImportError:
    _SHARED_ROTATION = False
    def _rotate_audit_files(*args, **kwargs):
        pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = Path.home()
INBOX_ROOT       = HOME / "inbox"
APPROVALS_DIR    = INBOX_ROOT / "_approvals"
ARCHIVE_DIR      = INBOX_ROOT / "archive"
AUDIT_ROOT       = INBOX_ROOT / "_audit"
ROLLBACK_ROOT    = INBOX_ROOT / "_rollback"
# FP-30.9 Wave 1 Fix 2 — dashboard poll directories.
# After processing an approval, the executor moves the approval file into one
# of these three subdirs. Dashboard (VibeIsland FixButton) polls these paths
# by approval filename (== execId from the UI) to resolve its result state.
PROCESSED_ROOT   = APPROVALS_DIR / "_processed"
PROCESSED_APPLIED = PROCESSED_ROOT / "applied"
PROCESSED_FAILED  = PROCESSED_ROOT / "failed"
PROCESSED_SKIPPED = PROCESSED_ROOT / "skipped"
# F3 (bigd-pipeline-repair Phase 3) RK4: 7-day grace landing pad for
# empty-command briefs that lack explicit action_type:"no_op". Routed here
# instead of failed/ until inbox_writer.py upgrades emit explicit no_op.
PROCESSED_TRANSITIONING = PROCESSED_ROOT / "transitioning"
# Grace anchor timestamp file: written on first run after deploy.
F3_GRACE_ANCHOR_PATH = PROCESSED_ROOT / ".f3_grace_anchor"
F3_GRACE_SEC = 7 * 24 * 3600  # 7 days


def _f3_within_grace() -> bool:
    """True if we're inside the 7-day F3 transition grace window.
    Anchor file is created on first call (idempotent).
    """
    try:
        PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
        if not F3_GRACE_ANCHOR_PATH.exists():
            F3_GRACE_ANCHOR_PATH.write_text(str(int(__import__('time').time())))
            return True
        anchor_ts = int(F3_GRACE_ANCHOR_PATH.read_text().strip() or "0")
        return (int(__import__('time').time()) - anchor_ts) <= F3_GRACE_SEC
    except (OSError, ValueError):
        return True  # fail-safe: stay in grace if anything is wrong

# ---------------------------------------------------------------------------
# Allowlisted path roots for file_delete / file_edit
# ---------------------------------------------------------------------------
ALLOWED_PATH_ROOTS = [
    HOME,
    HOME / "NardoWorld",
    HOME / ".claude",
]

# Absolute paths that are NEVER touchable (even if under an allowed root)
HARD_PROTECTED = [
    HOME / ".claude" / "hooks" / "approval_executor.py",  # self-protection
    HOME / ".ssh",
    HOME / ".gnupg",
    INBOX_ROOT / "_audit",
    INBOX_ROOT / "_rollback",
    INBOX_ROOT / "_approvals",
]

# ---------------------------------------------------------------------------
# Allowlist: maps action_type to validator + executor
# ---------------------------------------------------------------------------
# systemd/launchd unit patterns (mac-only executor runs locally)
PLIST_LABEL_RE = re.compile(r"^com\.bernard\.bigd-[a-z]+$")
SYSTEMD_UNIT_RE = re.compile(r"^(com\.bernard\.bigd-|bigd-)[a-z]+$")

# Allowlisted command regex patterns -> action_type inference
# Used for existing briefs that have free-text command fields.
# Each entry: (regex_pattern, action_type, notes)
_COMMAND_ALLOWLIST: list[tuple[re.Pattern, str, str]] = [
    # launchctl load/unload for bigd plists
    (re.compile(r"^launchctl\s+(load|unload)\s+~/Library/LaunchAgents/(com\.bernard\.bigd-[a-z]+)\.plist$"),
     "plist_reload", "bigd plist load/unload"),
    # launchctl kickstart for bigd labels
    (re.compile(r"^launchctl\s+kickstart\s+-k\s+gui/[0-9]+/(com\.bernard\.bigd-[a-z]+)$"),
     "launchd_enable", "bigd kickstart"),
    # launchctl bootout for bigd labels
    (re.compile(r"^launchctl\s+bootout\s+gui/[0-9]+/(com\.bernard\.bigd-[a-z]+)$"),
     "launchd_disable", "bigd bootout"),
    # cat / tail log commands -- read-only, allowed
    (re.compile(r"^(cat|tail)\s+~/[^\s;|&`$<>]+\.(log|jsonl|txt|md)(\s+-[a-z0-9 ]+)?$"),
     "no_op", "read-only log view -- no side effect"),
    # F3 (bigd-pipeline-repair Phase 3): r"^$" → no_op rule REMOVED.
    # Briefs that intend a true no-op MUST declare action_type:"no_op" on the
    # action itself (preferred via matched_action.get("action_type") at the
    # callsite). Empty-command actions without that field now route to
    # _processed/transitioning/ for 7 days (RK4 grace), then to failed/.
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "READ_ERROR"
    return h.hexdigest()


def _write_audit(entry: dict, dry_run: bool) -> None:
    """Append one line to today's audit JSONL. Always writes even in dry_run (tagged)."""
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    audit_path = AUDIT_ROOT / f"executor_{date_str}.jsonl"
    entry["dry_run"] = dry_run
    line = json.dumps(entry, default=str) + "\n"
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(line)


def _log(msg: str) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _resolve_safe(raw: str) -> Path | None:
    """
    Resolve ~-prefixed or absolute path.
    Returns None if path is outside all ALLOWED_PATH_ROOTS or inside HARD_PROTECTED.
    NO glob expansion (by design).
    """
    if "*" in raw or "?" in raw or "[" in raw:
        _log(f"REJECT path contains glob chars: {raw!r}")
        return None
    expanded = Path(os.path.expanduser(raw))
    try:
        resolved = expanded.resolve()
    except OSError:
        return None
    # Hard-protected check
    for hp in HARD_PROTECTED:
        try:
            resolved.relative_to(hp.resolve())
            _log(f"REJECT path in hard-protected zone: {resolved}")
            return None
        except ValueError:
            pass
    # Must be under at least one allowed root
    for root in ALLOWED_PATH_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            pass
    _log(f"REJECT path outside allowed roots: {resolved}")
    return None


# ---------------------------------------------------------------------------
# Action type inference from command string
# ---------------------------------------------------------------------------

def _infer_action_type(command: str) -> str:
    """
    Map a command string to an allowlisted action_type.
    Returns "REJECTED" if command matches no allowlisted pattern.
    """
    cmd = command.strip()
    for pattern, action_type, _ in _COMMAND_ALLOWLIST:
        if pattern.match(cmd):
            return action_type
    return "REJECTED"


# ---------------------------------------------------------------------------
# Gate class + GATES registry (FP-4)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Gate:
    """
    A single pre-execution gate check.

    check(brief) returns None on pass, or a reason string on failure.
    severity: "hard" (blocks execution) or "warn" (logged only, does not block).
    """
    name: str
    description: str
    severity: str  # "hard" | "warn"
    _check_fn: dataclasses.InitVar[object] = dataclasses.field(default=None)

    def __post_init__(self, _check_fn):
        self._fn = _check_fn

    def check(self, brief: dict) -> Optional[str]:
        """Return None (pass) or reason string (fail)."""
        try:
            return self._fn(brief)
        except Exception as exc:
            return f"gate_check_exception: {exc}"


@dataclasses.dataclass
class Blocked:
    """Result returned when a hard gate rejects an action."""
    gate_name: str
    reason: str


def _gate_v1_action_type_known(brief: dict) -> Optional[str]:
    """V1: action_type must be in allowlist (not REJECTED or unknown)."""
    action_type = brief.get("_resolved_action_type", "")
    if action_type == "REJECTED":
        return "action_type REJECTED: command not in allowlist"
    if not action_type:
        return "action_type is empty"
    return None


def _gate_v2_brief_id_present(brief: dict) -> Optional[str]:
    """V2: brief must have a non-empty brief_id."""
    if not brief.get("brief_id", "").strip():
        return "brief_id is missing or empty"
    return None


def _gate_v3_action_code_present(brief: dict) -> Optional[str]:
    """V3: approval must include a code that matches an action in the brief."""
    if not brief.get("_matched_action"):
        return "no action matched approval code in brief"
    return None


def _gate_v4_host_known(brief: dict) -> Optional[str]:
    """V4: host field must be in known set."""
    known_hosts = {"mac", "hel", "london", "github"}
    host = brief.get("host", "")
    if host and host not in known_hosts:
        return f"host {host!r} not in known hosts {known_hosts}"
    return None


def _gate_v5_no_orphaned_brief(brief: dict) -> Optional[str]:
    """V5: brief dict must not be None (brief was found in archive/inbox)."""
    if brief.get("_brief_missing"):
        return "brief not found in archive or inbox (orphaned approval)"
    return None


# Ordered list of gates — evaluated left to right; first hard-fail blocks.
GATES: list[Gate] = [
    Gate("V1", "action_type in allowlist",    "hard", _gate_v1_action_type_known),
    Gate("V2", "brief_id present",             "hard", _gate_v2_brief_id_present),
    Gate("V3", "action code matched",          "hard", _gate_v3_action_code_present),
    Gate("V4", "host is known",                "warn", _gate_v4_host_known),
    Gate("V5", "brief not orphaned",           "hard", _gate_v5_no_orphaned_brief),
]


def run_gates(context: dict) -> Optional[Blocked]:
    """
    Run all GATES against context dict.
    Returns Blocked(gate_name, reason) on first hard failure, None if all pass.
    """
    for gate in GATES:
        reason = gate.check(context)
        if reason and gate.severity == "hard":
            return Blocked(gate_name=gate.name, reason=reason)
    return None


# ---------------------------------------------------------------------------
# V1-V5 gates for file actions (original file-level gates, unchanged)
# ---------------------------------------------------------------------------

def _run_v1_v5_file(path: Path, exec_id: str, dry_run: bool) -> dict:
    """
    Run V1-V5 gates for file_delete / file_edit.
    Returns dict: gates + all_pass bool + pre_hash + rollback_path.
    """
    gates: dict[str, dict] = {}

    # V4: file exists + size plausible
    v4_pass = path.exists() and path.is_file()
    size = path.stat().st_size if v4_pass else -1
    v4_plausible = v4_pass and size < 500 * 1024 * 1024  # <500MB plausible
    gates["V4"] = {"pass": v4_plausible, "desc": f"file exists + size={size}"}

    pre_hash = _sha256_file(path) if v4_pass else "MISSING"

    # V1: backup to rollback dir
    rollback_dir = ROLLBACK_ROOT / exec_id / "original"
    rollback_path = str(rollback_dir / path.name)
    v1_pass = False
    if v4_pass and not dry_run:
        try:
            rollback_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, rollback_dir / path.name)
            # Also save original path for recovery
            meta_path = rollback_dir.parent / "meta.json"
            meta = {"original_path": str(path), "backup_file": rollback_path, "exec_id": exec_id}
            meta_path.write_text(json.dumps(meta, indent=2))
            v1_pass = True
        except OSError as e:
            gates["V1"] = {"pass": False, "desc": f"backup failed: {e}"}
    else:
        # dry-run: pretend backup ok
        v1_pass = v4_pass
        rollback_dir.mkdir(parents=True, exist_ok=True) if dry_run else None

    gates["V1"] = {"pass": v1_pass, "desc": f"backup to {rollback_path}"}

    # V2: dry-run verify (will action produce valid output)
    # For file_delete: file would be gone (trivially safe if v4 passes)
    # For file_edit: applied in temp copy -- done in action executor
    gates["V2"] = {"pass": True, "desc": "dry-run verify OK (action-specific check below)"}

    # V3: change preview -- diff logged in caller
    gates["V3"] = {"pass": True, "desc": "change preview written to audit log"}

    # V5: rollback script prepared
    rollback_script_path = ROLLBACK_ROOT / exec_id / "rollback.sh"
    rollback_script = (
        f"#!/bin/sh\n"
        f"# Auto-generated rollback for exec_id={exec_id}\n"
        f"set -e\n"
        f'cp -p "{rollback_path}" "{path}"\n'
        f'echo "Restored {path} from backup"\n'
    )
    v5_pass = False
    try:
        (ROLLBACK_ROOT / exec_id).mkdir(parents=True, exist_ok=True)
        rollback_script_path.write_text(rollback_script)
        rollback_script_path.chmod(0o700)
        v5_pass = True
    except OSError as e:
        pass
    gates["V5"] = {"pass": v5_pass, "desc": f"rollback script at {rollback_script_path}"}

    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "all_pass": all_pass,
        "pre_hash": pre_hash,
        "rollback_path": rollback_path,
        "rollback_script": str(rollback_script_path),
    }


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------

def _exec_file_delete(path: Path, exec_id: str, dry_run: bool) -> dict:
    """Execute file_delete. Returns result dict."""
    gates = _run_v1_v5_file(path, exec_id, dry_run)
    if not gates["all_pass"]:
        return {"ok": False, "reason": f"V1-V5 failed: {gates['gates']}", "gates": gates}

    pre_hash = gates["pre_hash"]
    preview = f"DELETE: {path} (size={path.stat().st_size if path.exists() else -1}, sha256={pre_hash[:16]}...)"

    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "gates": gates, "post_hash": "DRY_RUN"}

    try:
        path.unlink()
    except OSError as e:
        return {"ok": False, "reason": f"unlink failed: {e}", "gates": gates}

    post_hash = "DELETED"
    return {"ok": True, "preview": preview, "pre_hash": pre_hash, "post_hash": post_hash, "gates": gates}


def _exec_file_edit(path: Path, diff_str: str, exec_id: str, dry_run: bool) -> dict:
    """Execute file_edit by applying a unified diff. Returns result dict."""
    if not path.exists():
        return {"ok": False, "reason": f"target file not found: {path}"}

    gates = _run_v1_v5_file(path, exec_id, dry_run)
    if not gates["all_pass"]:
        return {"ok": False, "reason": f"V1-V5 failed: {gates['gates']}", "gates": gates}

    pre_hash = gates["pre_hash"]
    original_text = path.read_text(encoding="utf-8", errors="replace")

    # V2: apply diff to a temp file first (dry-run verification)
    with tempfile.NamedTemporaryFile(mode="w", suffix=path.suffix, delete=False, encoding="utf-8") as tmp:
        tmp.write(original_text)
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run(
            ["patch", "--dry-run", "-u", str(tmp_path)],
            input=diff_str,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            return {"ok": False, "reason": f"patch dry-run failed: {result.stderr[:200]}", "gates": gates}
    except FileNotFoundError:
        # patch not available -- fall back to difflib (read-only check)
        tmp_path.unlink(missing_ok=True)
        return {"ok": False, "reason": "patch binary not found -- cannot apply diff safely"}

    tmp_path.unlink(missing_ok=True)

    preview = diff_str[:500]
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "gates": gates}

    # Apply for real
    apply_result = subprocess.run(
        ["patch", "-u", str(path)],
        input=diff_str,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if apply_result.returncode != 0:
        return {"ok": False, "reason": f"patch apply failed: {apply_result.stderr[:200]}", "gates": gates}

    post_hash = _sha256_file(path)
    return {"ok": True, "preview": preview, "pre_hash": pre_hash, "post_hash": post_hash, "gates": gates}


def _exec_plist_reload(label: str, exec_id: str, dry_run: bool) -> dict:
    """Unload + load a com.bernard.bigd-* launchd plist on mac."""
    if not PLIST_LABEL_RE.match(label):
        return {"ok": False, "reason": f"REJECT label {label!r} does not match allowed pattern"}

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not plist_path.exists():
        return {"ok": False, "reason": f"plist not found: {plist_path}"}

    # V1-V5 for plist: simpler (no file content backup needed -- plist is config, not data)
    rollback_dir = ROLLBACK_ROOT / exec_id
    rollback_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plist_path, rollback_dir / plist_path.name)
    rollback_script = rollback_dir / "rollback.sh"
    rollback_script.write_text(
        f"#!/bin/sh\n"
        f"launchctl unload {plist_path}\n"
        f"launchctl load {plist_path}\n"
    )
    rollback_script.chmod(0o700)

    pre_hash = _sha256_file(plist_path)
    preview = f"plist_reload: unload+load {label}"

    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "pre_hash": pre_hash, "post_hash": "DRY_RUN"}

    for cmd in [["launchctl", "unload", str(plist_path)], ["launchctl", "load", str(plist_path)]]:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"ok": False, "reason": f"{' '.join(cmd)} failed: {r.stderr[:200]}"}

    return {"ok": True, "preview": preview, "pre_hash": pre_hash, "post_hash": pre_hash}


def _exec_launchd_enable(label: str, exec_id: str, dry_run: bool) -> dict:
    if not PLIST_LABEL_RE.match(label):
        return {"ok": False, "reason": f"REJECT label {label!r} does not match allowed pattern"}
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    preview = f"launchd_enable: launchctl load {label}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}
    r = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"ok": False, "reason": r.stderr[:200]}
    return {"ok": True, "preview": preview}


def _exec_launchd_disable(label: str, exec_id: str, dry_run: bool) -> dict:
    if not PLIST_LABEL_RE.match(label):
        return {"ok": False, "reason": f"REJECT label {label!r} does not match allowed pattern"}
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    preview = f"launchd_disable: launchctl unload {label}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}
    r = subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"ok": False, "reason": r.stderr[:200]}
    return {"ok": True, "preview": preview}


def _exec_inbox_archive(finding_id: str, exec_id: str, dry_run: bool) -> dict:
    """Move a finding from inbox tiers to archive."""
    # Validate finding_id format
    if not re.match(r"^[a-z0-9_-]+$", finding_id):
        return {"ok": False, "reason": f"REJECT finding_id {finding_id!r} contains invalid chars"}
    preview = f"inbox_archive: archive finding {finding_id}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}
    moved = False
    for subdir in ("critical", "daily", "weekly"):
        src = INBOX_ROOT / subdir / f"{finding_id}.json"
        if src.exists():
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), ARCHIVE_DIR / src.name)
            moved = True
            break
    if not moved:
        return {"ok": False, "reason": f"finding {finding_id} not found in inbox tiers"}
    return {"ok": True, "preview": preview}


# ---------------------------------------------------------------------------
# SSH-back host mapping (Phase 5 cross-host executor)
# ---------------------------------------------------------------------------
# Maps host field in brief -> SSH alias. Only hel and london need SSH.
_SSH_ALIAS_MAP: dict[str, str] = {
    "hel":    "hel",
    "london": "pm-london",
}

# Action types that must run on the origin host (not a local plan-write or no_op).
_REMOTE_ACTION_TYPES = {
    "file_delete",
    "file_edit",
    "plist_reload",      # systemd equivalent on VPS = systemd_reload
    "systemd_reload",
    "launchd_enable",
    "launchd_disable",
    "memory_cleanup",
    "disk_cleanup",
}


def _ssh_exec_action(ssh_alias: str, brief_id: str, action_type: str,
                     action_params: dict, command: str,
                     exec_id: str, dry_run: bool) -> dict:
    """
    SSH to origin host and execute an allowlisted action directly.

    Security:
    - Only SSHes to known aliases in _SSH_ALIAS_MAP.
    - Only action_types in _REMOTE_ACTION_TYPES are dispatched remotely.
    - Each action_type maps to a bounded, pre-approved remote command.
    - NO free-text shell exec: action_params values are validated before use.
    - Unit names validated against SYSTEMD_UNIT_RE before use in ssh command.
    """
    if action_type not in _REMOTE_ACTION_TYPES:
        return {"ok": False, "reason": f"ssh_exec: action_type {action_type!r} not in REMOTE_ACTION_TYPES"}

    if ssh_alias not in _SSH_ALIAS_MAP.values():
        return {"ok": False, "reason": f"ssh_exec: alias {ssh_alias!r} not in allowed SSH aliases"}

    # Build the remote command for each action type.
    # All commands are hardcoded patterns -- no user-controlled string interpolation.
    remote_cmd: str | None = None

    if action_type == "systemd_reload":
        unit = action_params.get("unit", action_params.get("label", ""))
        if not SYSTEMD_UNIT_RE.match(unit):
            return {"ok": False, "reason": f"ssh_exec systemd_reload: invalid unit {unit!r}"}
        if dry_run:
            remote_cmd = f"systemctl is-active {unit} && echo DRY-RUN-OK"
        else:
            remote_cmd = f"systemctl restart {unit} && echo restarted"

    elif action_type == "disk_cleanup":
        # Bounded: only /tmp, files older than 7 days
        if dry_run:
            remote_cmd = "find /tmp -maxdepth 1 -type f -mtime +7 | wc -l"
        else:
            remote_cmd = "find /tmp -maxdepth 1 -type f -mtime +7 -delete && echo cleanup-done"

    elif action_type == "memory_cleanup":
        # Linux: drop_caches = 1 (page cache)
        if dry_run:
            remote_cmd = "free -h && echo DRY-RUN-OK"
        else:
            remote_cmd = "sync && echo 1 > /proc/sys/vm/drop_caches && echo caches-dropped"

    elif action_type in ("file_delete", "file_edit",
                         "plist_reload", "launchd_enable", "launchd_disable"):
        # These action types don't make sense on a linux VPS.
        # file_delete/file_edit require validated paths -- defer to plan-write instead.
        return {
            "ok": False,
            "reason": (
                f"ssh_exec: action_type {action_type!r} on VPS ({ssh_alias}) requires manual review. "
                f"Use cred_rotate_plan or git_filter_repo_plan for destructive file ops."
            ),
        }
    else:
        return {"ok": False, "reason": f"ssh_exec: no remote command mapping for {action_type!r}"}

    preview = f"ssh_exec [{ssh_alias}]: {action_type} for {brief_id}"
    _log(f"  SSH dispatch: {ssh_alias} -> {remote_cmd[:80]}")

    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes",
             ssh_alias, remote_cmd],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return {
                "ok":    True,
                "preview": preview,
                "remote_stdout": result.stdout.strip()[:500],
            }
        else:
            return {
                "ok": False,
                "reason": f"ssh_exec: rc={result.returncode}: {result.stderr[:200]}",
                "remote_stdout": result.stdout[:200],
            }
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"ssh_exec: timeout waiting for {ssh_alias}"}
    except Exception as e:
        return {"ok": False, "reason": f"ssh_exec: exception: {e}"}


def _exec_no_op(brief_id: str, code: str, exec_id: str, dry_run: bool) -> dict:
    """Defer/skip -- record in audit log, no action taken."""
    return {"ok": True, "preview": f"no_op: code={code} for {brief_id} -- no action taken"}


def _exec_file_map_update(note: str, exec_id: str, dry_run: bool) -> dict:
    """
    Append a missing path note to the PM bot file-map.md.
    note: plain text entry to append (no shell expansion).
    Bounded: only appends, never deletes. <2KB per note.
    """
    # V1: note must be non-empty and <= 500 chars
    note = note.strip()
    if not note:
        return {"ok": False, "reason": "file_map_update: note is empty"}
    if len(note) > 500:
        return {"ok": False, "reason": f"file_map_update: note too long ({len(note)} chars, max 500)"}

    file_map = HOME / "NardoWorld" / "projects" / "prediction-markets" / "file-map.md"
    if not file_map.exists():
        return {"ok": False, "reason": f"file_map_update: file-map.md not found at {file_map}"}

    preview = f"file_map_update: append note to {file_map.name}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "note_preview": note[:100]}

    # V1: backup
    rollback_dir = ROLLBACK_ROOT / exec_id / "original"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_map, rollback_dir / file_map.name)

    now_iso = _now_utc()
    append_block = f"\n\n<!-- file_map_update appended by approval_executor at {now_iso} -->\n{note}\n"
    with open(file_map, "a", encoding="utf-8") as f:
        f.write(append_block)

    return {"ok": True, "preview": preview, "chars_appended": len(append_block)}


def _exec_memory_cleanup(exec_id: str, dry_run: bool) -> dict:
    """
    Run `sudo purge` on mac to free inactive memory.
    Guard: only runs on darwin. No-ops elsewhere.
    """
    import platform
    if platform.system() != "Darwin":
        return {"ok": False, "reason": "memory_cleanup: not on Darwin -- skipped"}

    preview = "memory_cleanup: sudo purge"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}

    result = subprocess.run(
        ["sudo", "purge"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {"ok": False, "reason": f"sudo purge failed (rc={result.returncode}): {result.stderr[:200]}"}
    return {"ok": True, "preview": preview, "stdout": result.stdout.strip()}


def _exec_disk_cleanup(exec_id: str, dry_run: bool) -> dict:
    """
    Delete /tmp files older than 7 days.
    Bounded: only /tmp, never $HOME or NardoWorld.
    """
    import platform
    import time as _time

    cutoff = _time.time() - 7 * 86400
    preview = "disk_cleanup: rm /tmp files >7d old"

    tmp_dir = Path("/tmp")
    to_delete: list[Path] = []
    try:
        for f in tmp_dir.iterdir():
            if f.is_file() and not f.is_symlink():
                try:
                    if f.stat().st_mtime < cutoff:
                        to_delete.append(f)
                except OSError:
                    pass
    except PermissionError as e:
        return {"ok": False, "reason": f"disk_cleanup: cannot scan /tmp: {e}"}

    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "would_delete": len(to_delete)}

    deleted = 0
    errors = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except OSError:
            errors += 1

    return {"ok": True, "preview": preview, "deleted": deleted, "errors": errors}


def _exec_git_filter_repo_plan(finding_id: str, exec_id: str, dry_run: bool) -> dict:
    """
    Write a git-filter-repo plan file to ~/inbox/_plans/ for user review.
    NEVER executes git-filter-repo directly. Human eye required.
    """
    plans_dir = HOME / "inbox" / "_plans"
    plan_path = plans_dir / f"git_filter_{finding_id}.sh"

    preview = f"git_filter_repo_plan: write plan to {plan_path}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}

    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_content = (
        f"#!/bin/sh\n"
        f"# git-filter-repo plan for finding_id={finding_id}\n"
        f"# AUTO-GENERATED by approval_executor -- DO NOT RUN without review\n"
        f"# generated: {_now_utc()}\n"
        f"#\n"
        f"# Steps to execute manually after review:\n"
        f"# 1. Install git-filter-repo: pip install git-filter-repo\n"
        f"# 2. Back up the repo: cp -r <repo> <repo>.bak\n"
        f"# 3. Run: git filter-repo --invert-paths --path <path-to-remove>\n"
        f"# 4. Force-push ONLY to your own fork with explicit consent.\n"
        f"#\n"
        f"# !! This script is a PLAN, not executable. Review every line first.\n"
    )
    if not plan_path.exists():
        plan_path.write_text(plan_content, encoding="utf-8")
        plan_path.chmod(0o600)

    return {"ok": True, "preview": preview, "plan_path": str(plan_path)}


def _exec_cred_rotate_plan(finding_id: str, exec_id: str, dry_run: bool) -> dict:
    """
    Write a credential rotation plan file to ~/inbox/_plans/ for user review.
    NEVER rotates credentials directly. Human eye required.
    """
    plans_dir = HOME / "inbox" / "_plans"
    plan_path = plans_dir / f"cred_rotate_{finding_id}.sh"

    preview = f"cred_rotate_plan: write plan to {plan_path}"
    if dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}

    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_content = (
        f"#!/bin/sh\n"
        f"# Credential rotation plan for finding_id={finding_id}\n"
        f"# AUTO-GENERATED by approval_executor -- DO NOT RUN without review\n"
        f"# generated: {_now_utc()}\n"
        f"#\n"
        f"# Steps to execute manually after review:\n"
        f"# 1. Identify exposed credential (see finding in ~/inbox/critical/{finding_id}.json)\n"
        f"# 2. Revoke old credential via provider dashboard\n"
        f"# 3. Generate new credential\n"
        f"# 4. Update ~/.env or relevant config file\n"
        f"# 5. Restart affected services\n"
        f"# 6. Verify old credential no longer works\n"
        f"#\n"
        f"# !! This script is a PLAN, not executable. Review every line first.\n"
    )
    if not plan_path.exists():
        plan_path.write_text(plan_content, encoding="utf-8")
        plan_path.chmod(0o600)

    return {"ok": True, "preview": preview, "plan_path": str(plan_path)}


# ---------------------------------------------------------------------------
# Brief lookup
# ---------------------------------------------------------------------------

def _load_brief_from_archive(brief_id: str) -> dict | None:
    """Look up a brief by id in archive/. Return brief dict or None."""
    pattern = str(ARCHIVE_DIR / "*.json")
    for path in glob.glob(pattern):
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("id") == brief_id:
            return data
    return None


def _load_brief_from_inbox(brief_id: str) -> dict | None:
    """Look up a brief by id in active inbox tiers. Return brief dict or None."""
    for subdir in ("critical", "daily", "weekly"):
        pattern = str(INBOX_ROOT / subdir / "*.json")
        for path in glob.glob(pattern):
            try:
                data = json.loads(Path(path).read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("id") == brief_id:
                return data
    return None


def _find_brief(brief_id: str) -> dict | None:
    """Find brief in archive first (acked briefs moved there), then inbox."""
    brief = _load_brief_from_archive(brief_id)
    if brief is None:
        brief = _load_brief_from_inbox(brief_id)
    return brief


# ---------------------------------------------------------------------------
# Structured action dispatch
# ---------------------------------------------------------------------------

def _dispatch_action(action_type: str, action_params: dict, brief_id: str,
                     code: str, exec_id: str, dry_run: bool) -> dict:
    """
    Dispatch to the correct executor based on action_type.
    action_params depends on action_type.
    """
    if action_type == "REJECTED":
        return {"ok": False, "reason": "ALLOWLIST VIOLATION: action_type REJECTED -- no matching allowlist pattern"}

    if action_type == "no_op":
        return _exec_no_op(brief_id, code, exec_id, dry_run)

    if action_type == "file_delete":
        raw_path = action_params.get("path", "")
        path = _resolve_safe(raw_path)
        if path is None:
            return {"ok": False, "reason": f"REJECT path_safety: {raw_path!r}"}
        return _exec_file_delete(path, exec_id, dry_run)

    if action_type == "file_edit":
        raw_path = action_params.get("path", "")
        diff_str = action_params.get("diff", "")
        path = _resolve_safe(raw_path)
        if path is None:
            return {"ok": False, "reason": f"REJECT path_safety: {raw_path!r}"}
        if not diff_str.strip():
            return {"ok": False, "reason": "file_edit requires non-empty diff"}
        return _exec_file_edit(path, diff_str, exec_id, dry_run)

    if action_type == "plist_reload":
        label = action_params.get("label", "")
        return _exec_plist_reload(label, exec_id, dry_run)

    if action_type == "launchd_enable":
        label = action_params.get("label", "")
        return _exec_launchd_enable(label, exec_id, dry_run)

    if action_type == "launchd_disable":
        label = action_params.get("label", "")
        return _exec_launchd_disable(label, exec_id, dry_run)

    if action_type == "inbox_archive":
        finding_id = action_params.get("finding_id", brief_id)
        return _exec_inbox_archive(finding_id, exec_id, dry_run)

    if action_type == "systemd_reload":
        # mac has launchd, not systemd -- redirect to plist_reload
        label = action_params.get("label", action_params.get("unit", ""))
        return _exec_plist_reload(label, exec_id, dry_run)

    if action_type == "file_map_update":
        note = action_params.get("note", "")
        return _exec_file_map_update(note, exec_id, dry_run)

    if action_type == "memory_cleanup":
        return _exec_memory_cleanup(exec_id, dry_run)

    if action_type == "disk_cleanup":
        return _exec_disk_cleanup(exec_id, dry_run)

    if action_type == "git_filter_repo_plan":
        finding_id = action_params.get("finding_id", brief_id)
        return _exec_git_filter_repo_plan(finding_id, exec_id, dry_run)

    if action_type == "cred_rotate_plan":
        finding_id = action_params.get("finding_id", brief_id)
        return _exec_cred_rotate_plan(finding_id, exec_id, dry_run)

    return {"ok": False, "reason": f"Unknown action_type: {action_type!r}"}


# ---------------------------------------------------------------------------
# Process one approval file
# ---------------------------------------------------------------------------

def _move_processed(approval_path: Path, record: dict, dry_run: bool) -> None:
    """
    FP-30.9 Wave 1 Fix 2: move a processed approval file into
    _processed/{applied,failed,skipped}/<filename> so the VibeIsland dashboard
    can poll by approval filename (execId) to resolve its result state.

    Also rewrites the file contents to include the audit record body so the
    dashboard can read `error` / `reason` / `ok` / `action_type` fields without
    a second audit-log lookup. Skipped entirely in dry-run mode.

    Routing:
      ok=True  AND action_type == no_op                  -> skipped/
      ok=True  otherwise                                  -> applied/
      ok=False AND (REJECTED | ORPHANED | NO_MATCHING_ACTION |
                    gate-blocked | parse_approval_failed) -> skipped/
      ok=False otherwise (actual exec failure)            -> failed/
    """
    if dry_run:
        return
    if not approval_path.exists():
        return

    ok = bool(record.get("ok"))
    atype = record.get("action_type") or ""
    gate_blocked = bool(record.get("gate_name")) and record.get("gate_name") != "PASS"
    parse_err = "parse_approval_failed" in str(record.get("error", ""))

    # F3 Phase 3: REJECTED + empty original command + grace window → transitioning/
    rejected_empty_cmd = (
        atype == "REJECTED"
        and not (record.get("command_rejected") or record.get("command") or "").strip()
    )
    if ok and atype == "no_op":
        dest_dir = PROCESSED_SKIPPED
    elif ok:
        dest_dir = PROCESSED_APPLIED
    elif rejected_empty_cmd and _f3_within_grace():
        dest_dir = PROCESSED_TRANSITIONING
    elif atype in ("REJECTED", "ORPHANED", "NO_MATCHING_ACTION") or gate_blocked or parse_err:
        dest_dir = PROCESSED_SKIPPED
    else:
        dest_dir = PROCESSED_FAILED

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / approval_path.name
        # Merge original approval body with audit record so dashboard gets both.
        merged: dict = {}
        try:
            merged.update(json.loads(approval_path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
        merged["_executor_result"] = record
        dest.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        approval_path.unlink()
    except OSError as e:
        _log(f"  WARN: failed to move processed approval {approval_path.name}: {e}")


def _process_approval(approval_path: Path, dry_run: bool) -> dict:
    """
    Process a single approval file end-to-end.
    Returns audit record dict.
    """
    # Rotate executor audit files (idempotent, non-fatal, runs once per invocation)
    if _SHARED_ROTATION:
        _rotate_audit_files("executor_*.jsonl", label="executor")

    exec_id = str(uuid.uuid4())[:8]
    ts_start = _now_utc()

    # Parse approval file
    try:
        approval = json.loads(approval_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {
            "exec_id": exec_id,
            "approval_path": str(approval_path),
            "error": f"parse_approval_failed: {e}",
            "ok": False,
            "timestamp": ts_start,
        }

    brief_id = approval.get("brief_id", "")
    code = approval.get("code", "")
    approved_by_ts = approval.get("timestamp", "")

    if not brief_id or not code:
        return {
            "exec_id": exec_id,
            "brief_id": brief_id,
            "error": "approval missing brief_id or code",
            "ok": False,
            "timestamp": ts_start,
        }

    # Look up brief
    brief = _find_brief(brief_id)
    if brief is None:
        _log(f"  WARN: brief {brief_id!r} not found in archive or inbox -- recording as orphaned")
        result = {
            "exec_id": exec_id,
            "brief_id": brief_id,
            "code": code,
            "approved_by_ts": approved_by_ts,
            "action_type": "ORPHANED",
            "ok": False,
            "reason": "brief not found",
            "timestamp": ts_start,
        }
        _write_audit(result, dry_run)
        return result

    # Find matching action in brief
    matched_action = None
    for act in brief.get("actions", []):
        if act.get("code") == code:
            matched_action = act
            break

    if matched_action is None:
        result = {
            "exec_id": exec_id,
            "brief_id": brief_id,
            "code": code,
            "approved_by_ts": approved_by_ts,
            "action_type": "NO_MATCHING_ACTION",
            "ok": False,
            "reason": f"no action with code={code!r} in brief",
            "timestamp": ts_start,
        }
        _write_audit(result, dry_run)
        return result

    action_label = matched_action.get("label", "")
    command = matched_action.get("command", "").strip()

    # Determine action_type: prefer explicit 'action_type' field (new briefs),
    # fall back to command-string inference (existing briefs).
    action_type = matched_action.get("action_type") or _infer_action_type(command)
    action_params = matched_action.get("action_params") or {}

    _log(f"  Processing: brief_id={brief_id!r} code={code!r} label={action_label!r}")
    _log(f"  action_type={action_type!r} command={command[:80]!r}")

    # FP-4: Run typed Gate checks. Build context dict from resolved state.
    gate_context = {
        "brief_id":              brief_id,
        "host":                  brief.get("host", ""),
        "_resolved_action_type": action_type,
        "_matched_action":       matched_action,
        "_brief_missing":        False,  # brief was found (would have exited above otherwise)
    }
    blocked = run_gates(gate_context)
    if blocked is not None:
        _log(f"  GATE {blocked.gate_name} BLOCKED: {blocked.reason}")
        result = {
            "exec_id": exec_id,
            "brief_id": brief_id,
            "code": code,
            "approved_by_ts": approved_by_ts,
            "action_type": action_type,
            "action_label": action_label,
            "command_rejected": command,
            "gate_name": blocked.gate_name,
            "ok": False,
            "reason": f"GATE {blocked.gate_name}: {blocked.reason}",
            "timestamp": ts_start,
        }
        _write_audit(result, dry_run)
        return result

    # Phase 5: Cross-host dispatch.
    # If the brief originated on a non-mac host AND the action must run on origin,
    # SSH back to the origin host and execute there instead of locally.
    brief_host = brief.get("host", "mac")
    ssh_alias  = _SSH_ALIAS_MAP.get(brief_host)
    if ssh_alias and action_type in _REMOTE_ACTION_TYPES:
        _log(f"  Cross-host dispatch: brief_host={brief_host!r} -> SSH alias={ssh_alias!r}")
        exec_result = _ssh_exec_action(
            ssh_alias, brief_id, action_type, action_params, command, exec_id, dry_run
        )
    else:
        # Dispatch locally (mac actions, plan-writes, no_ops)
        exec_result = _dispatch_action(action_type, action_params, brief_id, code, exec_id, dry_run)

    pre_hash = exec_result.get("gates", {}).get("pre_hash", exec_result.get("pre_hash", "N/A"))
    # Compatibility: pre_hash may be nested inside gates result
    if hasattr(exec_result.get("gates"), "get"):
        pre_hash = exec_result.get("pre_hash", "N/A")

    post_hash = exec_result.get("post_hash", "N/A")
    rollback_path = exec_result.get("rollback_path") or exec_result.get("gates", {}).get("rollback_path", "N/A")

    audit_record = {
        "exec_id": exec_id,
        "brief_id": brief_id,
        "code": code,
        "approved_by_ts": approved_by_ts,
        "action_type": action_type,
        "action_label": action_label,
        "command": command,
        "gate_name": "PASS",  # all gates passed to reach this point
        "pre_state_hash": pre_hash,
        "post_state_hash": post_hash,
        "rollback_path": rollback_path,
        "ok": exec_result.get("ok", False),
        "reason": exec_result.get("reason", ""),
        "preview": exec_result.get("preview", ""),
        "timestamp": ts_start,
    }

    _write_audit(audit_record, dry_run)

    status = "OK" if exec_result.get("ok") else "FAILED"
    _log(f"  Result: {status} -- {exec_result.get('reason') or exec_result.get('preview', '')}")

    return audit_record


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def _rollback(exec_id: str) -> None:
    """Execute rollback for a given exec_id."""
    rollback_dir = ROLLBACK_ROOT / exec_id
    rollback_script = rollback_dir / "rollback.sh"
    meta_path = rollback_dir / "original" / "meta.json"

    if not rollback_script.exists():
        _log(f"ROLLBACK FAIL: no rollback script found at {rollback_script}")
        sys.exit(1)

    _log(f"Rolling back exec_id={exec_id}")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        _log(f"  Restoring: {meta.get('backup_file')} -> {meta.get('original_path')}")

    result = subprocess.run(
        ["sh", str(rollback_script)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        _log(f"ROLLBACK OK: {result.stdout.strip()}")
    else:
        _log(f"ROLLBACK FAILED: {result.stderr.strip()}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# --from-verdict: generate approval files from verdict APPROVED decisions
# ---------------------------------------------------------------------------

VERDICTS_DIR = HOME / "inbox" / "_summaries" / "verdicts"


def _load_verdict_for_exec(verdict_id: str) -> dict | None:
    """
    Find and parse a verdict JSON in VERDICTS_DIR by verdict_id.
    Returns None if not found or unreadable.
    """
    for fpath in sorted(VERDICTS_DIR.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("verdict_id") == verdict_id:
            return data
    return None


def _generate_approval_files_from_verdict(verdict_id: str, dry_run: bool) -> list[Path]:
    """
    Read verdict, create one approval file per APPROVED decision.
    CLUSTERED decisions are skipped (meta-action handles them).
    Returns list of approval file paths created.

    Approval file format mirrors what _process_approval() expects:
      brief_id = action_id  (lookup in archive/inbox by action_id as brief_id)
      code = "VERDICT_APPROVED"

    Security: this function only reads the verdict from VERDICTS_DIR (controlled path).
    It does NOT execute shell commands; it only writes approval JSON files into
    APPROVALS_DIR which the existing V1-V5 gated executor then processes.
    """
    verdict = _load_verdict_for_exec(verdict_id)
    if verdict is None:
        _log(f"--from-verdict: verdict {verdict_id!r} not found in {VERDICTS_DIR}")
        sys.exit(1)

    # Validate expected keys
    if "decisions" not in verdict:
        _log(f"--from-verdict: verdict {verdict_id!r} missing 'decisions' field")
        sys.exit(1)

    # Collect CLUSTERED ids (never double-apply)
    clustered_ids: set[str] = {
        d["action_id"]
        for d in verdict["decisions"]
        if d.get("decision") == "CLUSTERED"
    }

    created: list[Path] = []
    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)

    for dec in verdict["decisions"]:
        action_id = dec.get("action_id", "")
        decision  = dec.get("decision", "")

        if decision != "APPROVED":
            _log(f"  SKIP {action_id!r} decision={decision!r}")
            continue

        if action_id in clustered_ids:
            _log(f"  SKIP {action_id!r} — in CLUSTERED set")
            continue

        if not dec.get("dependencies_met", True):
            _log(f"  SKIP {action_id!r} — dependencies_met=false")
            continue

        exec_id   = str(uuid.uuid4())[:8]
        ap_path   = APPROVALS_DIR / f"verdict_{exec_id}.json"
        approval  = {
            "brief_id":  action_id,
            "code":      "VERDICT_APPROVED",
            "timestamp": _now_utc(),
            "source":    f"from-verdict:{verdict_id}",
        }

        if dry_run:
            _log(f"  [DRY-RUN] would write approval file: {ap_path.name} for action_id={action_id!r}")
        else:
            ap_path.write_text(json.dumps(approval, indent=2), encoding="utf-8")
            _log(f"  wrote approval: {ap_path.name} for action_id={action_id!r}")
            created.append(ap_path)

    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="approval_executor.py -- Big SystemD P8-3 approval executor"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + validate approvals, write dry-run audit entries, DO NOT apply actions")
    parser.add_argument("--rollback", metavar="EXEC_ID",
                        help="Rollback a previously executed action by exec_id")
    parser.add_argument("--from-verdict", metavar="VERDICT_ID",
                        help="Generate approval files from APPROVED decisions in a verdict, then run exec loop")
    args = parser.parse_args()

    if args.rollback:
        _rollback(args.rollback)
        return

    dry_run = args.dry_run
    mode = "DRY-RUN" if dry_run else "LIVE"

    if args.from_verdict:
        # Phase 10.16 verdict path: generate approval files from verdict, process ONLY those files.
        # Does NOT touch the broader _approvals/ backlog — verdict actions are isolated.
        verdict_id = args.from_verdict
        _log(f"approval_executor starting [{mode}] --from-verdict={verdict_id!r}")
        created = _generate_approval_files_from_verdict(verdict_id, dry_run)
        if dry_run:
            _log("--from-verdict [DRY-RUN]: approval file generation previewed; exec loop skipped")
            return
        if not created:
            _log("--from-verdict: no approval files created (no APPROVED decisions or all skipped)")
            return
        # Process ONLY the verdict-generated files (not the full backlog)
        approval_files = [str(p) for p in sorted(created)]
        _log(f"--from-verdict: processing {len(approval_files)} verdict-generated approval file(s)")
    else:
        _log(f"approval_executor starting [{mode}]")
        pattern = str(APPROVALS_DIR / "*.json")
        approval_files = sorted(
            f for f in glob.glob(pattern)
            if not os.path.basename(f).startswith(".")
            # FP-30.9 Wave 1 Fix 2: never recurse into the _processed/ archive
            # (glob on *.json already excludes the subdir, but belt-and-braces
            # in case a future glob change widens to ** — reject anything under
            # _processed/ explicitly).
            and "_processed" not in Path(f).parts
        )

    if not approval_files:
        _log("No approval files found -- nothing to process")
        return

    _log(f"Found {len(approval_files)} approval file(s)")

    results = {"ok": 0, "failed": 0, "rejected": 0, "no_op": 0}

    for ap in approval_files:
        _log(f"Processing: {os.path.basename(ap)}")
        ap_path = Path(ap)
        record = _process_approval(ap_path, dry_run)
        # FP-30.9 Wave 1 Fix 2: relocate the processed approval so the
        # dashboard can poll by execId (= approval filename) for status.
        _move_processed(ap_path, record, dry_run)
        if not record.get("ok"):
            if record.get("action_type") == "REJECTED":
                results["rejected"] += 1
            else:
                results["failed"] += 1
        elif record.get("action_type") == "no_op":
            results["no_op"] += 1
        else:
            results["ok"] += 1

    _log(
        f"Done. ok={results['ok']} no_op={results['no_op']} "
        f"failed={results['failed']} rejected={results['rejected']}"
    )


if __name__ == "__main__":
    main()

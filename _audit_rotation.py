#!/usr/bin/env python3
"""
_audit_rotation.py — shared audit-log rotation helper.

Used by verdict.py and approval_executor.py to apply the same
retention policy to ~/inbox/_audit/*.jsonl files.

Policy:
  - JSONL files matching the glob older than GZIP_AFTER_DAYS (30):
      gzip into ~/inbox/_audit/_archive/
  - .gz archives older than DELETE_AFTER_DAYS (90): hard-delete.

Callable as a function (preferred) or as __main__ for one-shot runs.
"""
from __future__ import annotations

import gzip
import sys
from datetime import datetime, timezone
from pathlib import Path

GZIP_AFTER_DAYS   = 30
DELETE_AFTER_DAYS = 90

_AUDIT_ROOT    = Path.home() / "inbox" / "_audit"
_ARCHIVE_DIR   = _AUDIT_ROOT / "_archive"


def rotate_audit_files(glob_pattern: str, label: str = "audit") -> None:
    """
    Rotate JSONL audit files matching glob_pattern inside ~/inbox/_audit/.

    Args:
        glob_pattern: glob relative to _AUDIT_ROOT, e.g. "executor_*.jsonl"
        label:        prefix for stderr messages, e.g. "executor" or "verdict"

    Idempotent and silent on any I/O error (non-fatal by design).
    """
    try:
        if not _AUDIT_ROOT.exists():
            return
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        now_ts = datetime.now(tz=timezone.utc).timestamp()

        # Gzip old JSONL files
        for f in _AUDIT_ROOT.glob(glob_pattern):
            age_days = (now_ts - f.stat().st_mtime) / 86400
            if age_days >= GZIP_AFTER_DAYS:
                dest = _ARCHIVE_DIR / (f.name + ".gz")
                if not dest.exists():
                    with f.open("rb") as src_fh, gzip.open(dest, "wb") as gz_fh:
                        gz_fh.write(src_fh.read())
                f.unlink(missing_ok=True)
                print(
                    f"[{label}] audit rotate: gzipped {f.name} -> {dest.name}",
                    file=sys.stderr,
                )

        # Delete old .gz archives
        for gz in _ARCHIVE_DIR.glob("*.gz"):
            age_days = (now_ts - gz.stat().st_mtime) / 86400
            if age_days >= DELETE_AFTER_DAYS:
                gz.unlink(missing_ok=True)
                print(
                    f"[{label}] audit rotate: deleted {gz.name} (age={age_days:.0f}d)",
                    file=sys.stderr,
                )
    except Exception as exc:
        print(f"[{label}] audit rotate error (non-fatal): {exc}", file=sys.stderr)


if __name__ == "__main__":
    # One-shot: rotate both executor and fail_closed files.
    rotate_audit_files("executor_*.jsonl",    label="executor")
    rotate_audit_files("fail_closed_*.jsonl", label="verdict")
    print("Rotation complete.", file=sys.stderr)

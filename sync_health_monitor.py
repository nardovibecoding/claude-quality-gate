#!/usr/bin/env python3
"""SessionStart hook: check mem→wiki→graph pipeline health."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VPS = "bernard@157.180.28.14"
SSH_TIMEOUT = 3
DIFF_THRESHOLD = 5

LOCAL_MEMORY = Path.home() / ".claude" / "memory"
LOCAL_WIKI = Path.home() / "NardoWorld"
LAST_FILED = Path.home() / "NardoWorld" / "meta" / "last_filed"


def ssh_count(remote_dir: str) -> int | None:
    """Return file count on VPS, or None on failure."""
    try:
        result = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={SSH_TIMEOUT}",
             "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes",
             VPS, f"find {remote_dir} -type f 2>/dev/null | wc -l"],
            capture_output=True, text=True, timeout=SSH_TIMEOUT + 1
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


def local_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.rglob("*") if _.is_file())


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    warnings = []

    # 1. Check memory sync
    local_mem = local_count(LOCAL_MEMORY)
    vps_mem = ssh_count("~/claude-memory")
    if vps_mem is None:
        warnings.append("SSH to VPS failed — sync status unknown")
    else:
        diff = abs(local_mem - vps_mem)
        if diff > DIFF_THRESHOLD:
            warnings.append(
                f"Memory sync gap: local={local_mem} vs VPS={vps_mem} ({diff} files diff)"
            )

    # 2. Check NardoWorld sync
    if vps_mem is not None:  # SSH works, so check wiki too
        local_wiki = local_count(LOCAL_WIKI)
        vps_wiki = ssh_count("~/NardoWorld")
        if vps_wiki is not None:
            diff = abs(local_wiki - vps_wiki)
            if diff > DIFF_THRESHOLD:
                warnings.append(
                    f"NardoWorld sync gap: local={local_wiki} vs VPS={vps_wiki} ({diff} files diff)"
                )

    # 3. Check last_filed timestamp
    if LAST_FILED.exists():
        try:
            ts_str = LAST_FILED.read_text().strip()
            # Support ISO format or unix timestamp
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                ts = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_hours > 24:
                warnings.append(
                    f"Wiki filing may be stale (last filed {age_hours:.0f}h ago)"
                )
        except Exception:
            warnings.append("Could not parse ~/NardoWorld/meta/last_filed timestamp")
    else:
        warnings.append("~/NardoWorld/meta/last_filed missing — wiki filing untracked")

    # 4. Check VPS backup freshness
    if vps_mem is not None:
        try:
            result = subprocess.run(
                ["ssh", "-o", f"ConnectTimeout={SSH_TIMEOUT}",
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "BatchMode=yes",
                 VPS,
                 "find ~/vps-backup -type f -newer ~/vps-backup -mtime -1 2>/dev/null | wc -l; "
                 "[ -d ~/vps-backup ] && echo exists || echo missing"],
                capture_output=True, text=True, timeout=SSH_TIMEOUT + 1
            )
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                if len(lines) >= 2:
                    recent_count = int(lines[0].strip())
                    exists = lines[1].strip()
                    if exists == "missing":
                        warnings.append("VPS ~/vps-backup/ does not exist")
                    elif recent_count == 0:
                        warnings.append("VPS backup stale — no files modified today in ~/vps-backup/")
        except Exception:
            pass

    if warnings:
        msg = "Sync health issues:\n" + "\n".join(f"  - {w}" for w in warnings)
        print(json.dumps({"systemMessage": msg}))
    else:
        print("{}")


if __name__ == "__main__":
    main()

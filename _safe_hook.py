"""Shared hook safety wrapper — swallows exceptions, logs to file, exits 0."""
import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG = Path("/tmp/claude_hooks_errors.log")


def safe_run(main_fn, hook_name: str = ""):
    try:
        main_fn()
    except SystemExit:
        raise
    except Exception:
        name = hook_name or Path(sys.argv[0]).name
        try:
            with open(LOG, "a") as f:
                f.write(f"\n[{datetime.now().isoformat()}] {name}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        print("{}")
        sys.exit(0)

#!/usr/bin/env python3
"""Persistent hook daemon — eliminates python3 startup cost per tool call.

Listens on /tmp/claude_hook_daemon.sock. Clients send JSON events, get JSON responses.
All hook modules pre-loaded in memory. Runs as long as the Claude session lives.

Start: python3 hook_daemon.py &
Stop:  kill $(cat /tmp/claude_hook_daemon.pid) or auto-killed on session end
"""
import importlib.util
import io
import json
import os
import signal
import socket
import sys
import threading
from pathlib import Path

SOCK_PATH = "/tmp/claude_hook_daemon.sock"
PID_PATH = "/tmp/claude_hook_daemon.pid"
HOOKS_DIR = Path(__file__).parent

# ── Routing tables (same as dispatchers) ──

PRE_ROUTING = {
    "Bash": [
        "guard_safety.py", "auto_pre_publish.py", "unicode_grep_warn.py",
        "vps_setup_guard.py",
    ],
    "Edit": [
        "guard_safety.py", "file_lock.py", "pre_edit_impact.py",
        "skill_disable_not_delete.py", "memory_conflict_guard.py",
    ],
    "Write": [
        "guard_safety.py", "file_lock.py", "skill_disable_not_delete.py",
        "memory_conflict_guard.py",
    ],
    "Grep": [
        "unicode_grep_warn.py", "auto_recall.py",
    ],
    "Glob": [
        "auto_recall.py",
    ],
    "Agent": [
        "agent_cascade_guard.py", "agent_count_guard.py",
        "agent_simplicity_guard.py", "agent_tracker.py",
    ],
    "Skill": [
        "skill_enable_hook.py",
    ],
}

PRE_TOOL_INPUT_HOOKS = {
    "api_key_lookup.py": ["Bash", "Grep", "Read"],
}

# Wildcard pre hooks (run on every tool call)
PRE_WILDCARD = [
    "auto_save_inject.py",
    "auto_memory_inject.py",
]

POST_ROUTING = {
    "Edit": [
        "file_unlock.py", "auto_pip_install.py", "auto_memory_index.py",
        "auto_skill_sync.py", "auto_bot_restart.py", "auto_dependency_grep.py",
        "reasoning_leak_canary.py",
        "async_safety_guard.py", "hardcoded_model_guard.py",
        "resource_leak_guard.py", "temp_file_guard.py",
        "auto_test_after_edit.py",
    ],
    "Write": [
        "file_unlock.py", "auto_memory_index.py", "auto_copyright_header.py",
        "auto_dependency_grep.py",
        "async_safety_guard.py", "hardcoded_model_guard.py",
        "resource_leak_guard.py", "temp_file_guard.py",
        "auto_test_after_edit.py",
    ],
    "Bash": [
        "auto_dependency_grep.py", "auto_restart_process.py",
        "pre_commit_validate.py",
    ],
    "Read": [
        "memory_access_tracker.py", "memory_conflict_guard.py",
    ],
    "Skill": [
        "skill_disable_hook.py",
    ],
}

# ── Module cache ──

_module_cache = {}


def get_module(script_name):
    """Load and cache a hook module."""
    if script_name in _module_cache:
        return _module_cache[script_name]

    path = HOOKS_DIR / script_name
    if not path.exists():
        _module_cache[script_name] = None
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            script_name.replace(".py", ""), path
        )
        if not spec or not spec.loader:
            _module_cache[script_name] = None
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module_cache[script_name] = mod
    except Exception:
        _module_cache[script_name] = None

    return _module_cache[script_name]


def run_hook(script_name, event_data):
    """Run a hook's main() with faked stdin/stdout."""
    mod = get_module(script_name)
    if not mod or not hasattr(mod, "main"):
        return None

    old_stdin = sys.stdin
    old_stdout = sys.stdout
    sys.stdin = io.StringIO(json.dumps(event_data))
    captured = io.StringIO()
    sys.stdout = captured

    try:
        mod.main()
    except SystemExit:
        pass
    except Exception:
        pass
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    output = captured.getvalue().strip()
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass
    return None


def dispatch(event_data, routing, wildcard=None, tool_input_hooks=None):
    """Run hooks based on routing table, return merged result."""
    tool_name = event_data.get("tool_name", "")

    hooks_to_run = list(wildcard or [])
    if tool_name in routing:
        hooks_to_run.extend(routing[tool_name])

    if tool_input_hooks:
        for script, tools in tool_input_hooks.items():
            if tool_name in tools:
                hooks_to_run.append(script)

    if not hooks_to_run:
        return {}

    merged = {}
    for script in hooks_to_run:
        result = run_hook(script, event_data)
        if result:
            decision = result.get("decision", "")
            if decision in ("block", "deny"):
                return result

            if "additionalContext" in result:
                if "additionalContext" in merged:
                    merged["additionalContext"] += "\n" + result["additionalContext"]
                else:
                    merged["additionalContext"] = result["additionalContext"]
            for k, v in result.items():
                if k != "additionalContext":
                    merged[k] = v

    return merged


def handle_request(data_bytes):
    """Parse request, route to pre/post dispatch, return JSON response."""
    try:
        request = json.loads(data_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return b"{}\n"

    event_type = request.get("_event", "")  # "pre" or "post"
    event_data = request.get("_data", request)

    if event_type == "pre":
        result = dispatch(event_data, PRE_ROUTING, PRE_WILDCARD, PRE_TOOL_INPUT_HOOKS)
    elif event_type == "post":
        result = dispatch(event_data, POST_ROUTING)
    else:
        # Auto-detect: if has tool_result key, it's post
        if "tool_result" in event_data:
            result = dispatch(event_data, POST_ROUTING)
        else:
            result = dispatch(event_data, PRE_ROUTING, PRE_WILDCARD, PRE_TOOL_INPUT_HOOKS)

    return (json.dumps(result) + "\n").encode("utf-8")


def handle_client(conn):
    """Handle a single client connection."""
    try:
        chunks = []
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        if data:
            response = handle_request(data)
            conn.sendall(response)
    except Exception:
        try:
            conn.sendall(b"{}\n")
        except Exception:
            pass
    finally:
        conn.close()


def cleanup(*_):
    """Remove socket and pid file on exit."""
    try:
        os.unlink(SOCK_PATH)
    except OSError:
        pass
    try:
        os.unlink(PID_PATH)
    except OSError:
        pass
    sys.exit(0)


def preload_modules():
    """Pre-load all hook modules into cache."""
    all_scripts = set()
    for scripts in PRE_ROUTING.values():
        all_scripts.update(scripts)
    for scripts in POST_ROUTING.values():
        all_scripts.update(scripts)
    all_scripts.update(PRE_WILDCARD)
    for script in PRE_TOOL_INPUT_HOOKS:
        all_scripts.add(script)

    loaded = 0
    for script in sorted(all_scripts):
        if get_module(script):
            loaded += 1

    return loaded, len(all_scripts)


def main():
    # Clean up any stale socket
    try:
        os.unlink(SOCK_PATH)
    except OSError:
        pass

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    # Write PID
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    # Pre-load all modules
    loaded, total = preload_modules()

    # Start listening
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o600)
    sock.listen(8)
    sock.settimeout(1.0)  # Allow periodic check for signals

    sys.stderr.write(f"hook_daemon: loaded {loaded}/{total} hooks, listening on {SOCK_PATH}\n")

    while True:
        try:
            conn, _ = sock.accept()
            # Handle in thread to not block
            t = threading.Thread(target=handle_client, args=(conn,), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except Exception:
            continue


if __name__ == "__main__":
    main()

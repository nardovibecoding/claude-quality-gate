#!/usr/bin/env python3
"""Stop hook: detect story-worthy sessions via passive signals + write draft."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SIGNALS = {
    "INSPIRED_BY":   [r"check this (link|video|tweet)", r"got me thinking", r"saw this"],
    "BUILD_INTENT":  [r"i wanna build", r"lets? make", r"lets? create", r"new function"],
    "STEAL_ADAPT":   [r"(steal|adopt|adjust|improve|upgrade)"],
    "REVAMP":        [r"revamp", r"redesign", r"rethink", r"overhaul"],
    "WHAT_IF":       [r"what if we", r"imagine if", r"what about"],
    "EUREKA":        [r"\boh!\b", r"wait that means", r"\baha\b"],
    "REVERSED":      [r"actually no", r"\bopposite\b", r"scratch that"],
    "STORY_AWARE":   [r"this is a story", r"that'?s a story", r"worth telling"],
    "PIVOT":         [r"actually wait", r"but what about", r"hmm actually"],
    "CONNECT_DOTS":  [r"this is like", r"similar to", r"reminds me of"],
}


def get_transcript_path():
    status = Path("/tmp/claude_statusline.json")
    if status.exists():
        try:
            d = json.loads(status.read_text())
            tp = d.get("transcript_path")
            if tp and Path(tp).exists():
                return Path(tp)
        except Exception:
            pass
    return None


def read_last_messages(path, n=10):
    """Read last n lines from JSONL, extract user messages."""
    messages = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 32768)
            f.seek(max(0, size - chunk))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [l.strip() for l in tail.splitlines() if l.strip()]
        for line in lines[-50:]:
            try:
                obj = json.loads(line)
                role = obj.get("role", "")
                # handle both {"role":"user","content":"..."} and nested content arrays
                if role == "user":
                    content = obj.get("content", "")
                    if isinstance(content, list):
                        text = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    else:
                        text = str(content)
                    if text.strip():
                        messages.append(text)
            except Exception:
                pass
    except Exception:
        pass
    return messages[-n:]


def detect_signals(messages):
    found = {}  # signal_name -> [matched_text]
    texts = [m.lower() for m in messages]

    for name, patterns in SIGNALS.items():
        for text in texts:
            for pat in patterns:
                if re.search(pat, text):
                    found.setdefault(name, []).append(text[:80])
                    break
            if name in found:
                break  # one hit per signal type is enough

    # RABBIT_HOLE: any single message with 3+ ideas (3+ sentences or bullet items)
    for msg in messages:
        sentences = re.split(r"[.!?\n]|(?:^|\s)-\s", msg)
        ideas = [s for s in sentences if len(s.strip()) > 15]
        if len(ideas) >= 3:
            found.setdefault("RABBIT_HOLE", []).append(msg[:80])
            break

    # PATTERN_MATCH: referencing external inspiration + own system keywords
    system_kw = r"(my bot|our system|our bot|the pipeline|the hook|my setup)"
    ext_kw = r"(twitter|youtube|reddit|article|post|someone|they do|they use)"
    for msg in messages:
        ml = msg.lower()
        if re.search(system_kw, ml) and re.search(ext_kw, ml):
            found.setdefault("PATTERN_MATCH", []).append(msg[:80])
            break

    return found


def guess_topic(messages):
    """2-3 word topic from combined user messages."""
    combined = " ".join(messages).lower()
    # look for explicit subject nouns near build/revamp signals
    patterns = [
        r"(?:build|make|create|revamp|redesign)\s+(?:a\s+)?(\w+(?:\s+\w+)?)",
        r"(?:new\s+)(\w+(?:\s+\w+)?)\s+(?:system|bot|feature|function|tool)",
        r"(?:thinking about|idea for)\s+(\w+(?:\s+\w+){0,2})",
    ]
    for pat in patterns:
        m = re.search(pat, combined)
        if m:
            topic = m.group(1).strip()
            words = topic.split()[:3]
            topic = "-".join(words)
            if len(topic) > 3:
                return topic
    # fallback: first 3 significant words from first message
    words = re.findall(r"\b[a-z]{4,}\b", combined)
    stop = {"this", "that", "with", "have", "what", "from", "just", "like", "will", "want"}
    clean = [w for w in words if w not in stop][:3]
    return "-".join(clean) if clean else "untitled"


def write_draft(topic, signals, messages, date_str):
    stories_dir = Path.home() / "NardoWorld/stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    fname = f"draft_{date_str}_{topic}.md"
    path = stories_dir / fname

    beats = []
    for msg in messages:
        msg = msg.strip()
        if msg:
            beats.append(f"- {msg[:200]}")

    signal_list = list(signals.keys())
    frontmatter = f"""---
title: "{topic.replace('-', ' ')}"
date: {date_str}
status: draft
signals: {json.dumps(signal_list)}
---

## Story Beats

{chr(10).join(beats)}
"""
    path.write_text(frontmatter)
    return fname


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    stop_reason = hook_input.get("stop_reason", "")
    if stop_reason in ("error", "api_error"):
        print("{}")
        return

    session_id = hook_input.get("session_id", "unknown")
    marker = Path(f"/tmp/claude_story_{session_id}")
    if marker.exists():
        print("{}")
        return

    transcript_path = None

    # Try hook_input first
    tp = hook_input.get("transcript_path")
    if tp and Path(tp).exists():
        transcript_path = Path(tp)

    # Fallback: statusline json
    if not transcript_path:
        transcript_path = get_transcript_path()

    if not transcript_path:
        print("{}")
        return

    messages = read_last_messages(transcript_path, n=10)
    if not messages:
        print("{}")
        return

    signals = detect_signals(messages)

    if len(signals) < 3:
        print("{}")
        return

    # Enough signals -- write draft
    date_str = datetime.now().strftime("%Y-%m-%d")
    topic = guess_topic(messages)
    fname = write_draft(topic, signals, messages, date_str)

    # Mark session so we don't duplicate
    try:
        marker.write_text(fname)
    except Exception:
        pass

    result = {
        "systemMessage": f"Story detected: {topic}. Draft saved: ~/NardoWorld/stories/{fname}"
    }
    print(json.dumps(result))


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from _safe_hook import safe_run
    safe_run(main, "story_detector")

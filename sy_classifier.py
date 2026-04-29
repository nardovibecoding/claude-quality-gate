#!/usr/bin/env python3
"""
sy_classifier.py — content + scenario classifier for [SY] suggestions.

Given a candidate sy_text (and optional scenario hints), score the probability
Bernard would accept it without clarifying. Output:
  {accept_score: 0.0-1.0, action: 'auto_go'|'ask_normally'|'extra_caution', reasons: [...]}

Rule-based, not LLM. Calibrated against ~/NardoWorld/meta/sy_pairs.jsonl.

Usage:
  python3 sy_classifier.py "O1 — orthogonal, free, 5 min"
  python3 sy_classifier.py --eval   # backtest against labeled data
  python3 sy_classifier.py --json '{"sy_text": "..."}' # programmatic
"""

import json
import re
import sys
from pathlib import Path

PAIRS_FILE = Path.home() / "NardoWorld" / "meta" / "sy_pairs.jsonl"

# Features tuned from observed acceptance rates on 471 labeled pairs.
# Positive features push toward accept; negative push toward clarify/reject.
POSITIVE_FEATURES = [
    # (name, regex, weight, observed_accept_rate, n)
    ("orthogonal",   re.compile(r'\borthogonal\b', re.I),                              +0.25, 1.00,   4),
    ("no_overlap",   re.compile(r"\b(no overlap|don'?t overlap|independent|isolated)\b", re.I), +0.20, 0.83,  6),
    ("unblock",      re.compile(r'\b(unblock|unblocks|prerequisite)\b', re.I),         +0.15, 0.75,  12),
    ("reversible",   re.compile(r'\b(rollback|revert|reversible|dry.?run|preview|snapshot)\b', re.I), +0.12, 0.67, 12),
    ("free_cheap",   re.compile(r'\b(free|cheap|trivial|small|quick|2 min|5 min|10 min|fire and forget)\b', re.I), +0.08, 0.62, 71),
    ("scoped",       re.compile(r'\b(scope|scoping|plan|design)\b', re.I),             +0.05, 0.54,  157),
    ("commit_only",  re.compile(r'\b(commit|save|checkpoint|snapshot|preserve)\b', re.I), +0.05, 0.49, 41),
]

NEGATIVE_FEATURES = [
    ("destructive",  re.compile(r'\b(delete|drop|wipe|destructive|truncate|purge)\b', re.I), -0.30, "high reject risk"),
    ("force_op",     re.compile(r'\b(force|--force|reset.*hard|hard reset|overwrite)\b', re.I), -0.30, "irreversible op"),
    ("untested",     re.compile(r'\b(untested|haven\'?t tested|no test|not verified)\b', re.I), -0.20, "verification gap"),
    ("guess",        re.compile(r'\b(guess|maybe|might work|i think|probably)\b', re.I), -0.15, "low confidence"),
    ("audit_only",   re.compile(r'\b(audit|check|verify|inspect|examine|review)\b', re.I), -0.05, "tends toward clarify"),
]

# Hard-block patterns — never auto_go regardless of score
HARD_BLOCK = [
    re.compile(p, re.I) for p in [
        r'\b(wallet|private[\s_]?key|\.env|credential|secret|api[\s_]?key)\b',
        r'\bgit\s+push\s+(--force|origin)',
        r'\b(rm\s+-rf|drop\s+table|truncate)\b',
        r'\b(deploy.*prod|prod.*deploy|systemctl\s+(stop|restart))\b',
        r'\bclaude\.md\b',
    ]
]

# Thresholds (calibrated for high precision on auto_go)
AUTO_GO_THRESHOLD = 0.65       # rule-based score required for auto_go
ASK_NORMALLY_THRESHOLD = 0.40  # below this → extra_caution


def score_sy(sy_text, scenario=None):
    """
    Score an SY suggestion. Returns dict with accept_score, action, reasons, hard_blocked.
    scenario (optional): {recent_accept_rate: 0.0-1.0, in_approval_loop: bool}
    """
    text = sy_text or ""
    score = 0.50  # neutral prior
    reasons = []

    # Hard block check
    for pat in HARD_BLOCK:
        if pat.search(text):
            return {
                "accept_score": 0.0,
                "action": "extra_caution",
                "reasons": [f"hard_block: matches {pat.pattern[:40]}"],
                "hard_blocked": True,
            }

    for name, pat, weight, _, _ in POSITIVE_FEATURES:
        if pat.search(text):
            score += weight
            reasons.append(f"+{weight:.2f} {name}")

    for name, pat, weight, why in NEGATIVE_FEATURES:
        if pat.search(text):
            score += weight
            reasons.append(f"{weight:+.2f} {name} ({why})")

    # Scenario boosts
    if scenario:
        rar = scenario.get("recent_accept_rate")
        if rar is not None:
            adj = (rar - 0.50) * 0.20  # ±0.10 max
            score += adj
            reasons.append(f"{adj:+.2f} recent_accept_rate={rar:.2f}")
        if scenario.get("in_approval_loop"):
            score += 0.05
            reasons.append("+0.05 in_approval_loop")

    score = max(0.0, min(1.0, score))

    if score >= AUTO_GO_THRESHOLD:
        action = "auto_go"
    elif score >= ASK_NORMALLY_THRESHOLD:
        action = "ask_normally"
    else:
        action = "extra_caution"

    return {
        "accept_score": round(score, 3),
        "action": action,
        "reasons": reasons,
        "hard_blocked": False,
    }


def evaluate():
    """Backtest classifier against labeled pairs."""
    if not PAIRS_FILE.exists():
        print(f"sy_pairs.jsonl not found at {PAIRS_FILE}")
        sys.exit(1)
    pairs = [json.loads(l) for l in open(PAIRS_FILE) if l.strip()]
    decided = [p for p in pairs if p.get("signal") in ("accept", "clarify", "reject")]

    auto_go_correct = auto_go_wrong = 0
    auto_go_decisions = 0
    by_action = {"auto_go": [0, 0, 0], "ask_normally": [0, 0, 0], "extra_caution": [0, 0, 0]}
    # by_action: [accept, clarify, reject]

    for p in decided:
        result = score_sy(p.get("sy_text", ""))
        actual = p["signal"]
        action = result["action"]
        idx = {"accept": 0, "clarify": 1, "reject": 2}[actual]
        by_action[action][idx] += 1

        # auto_go precision: how often does auto_go match a real accept?
        if action == "auto_go":
            auto_go_decisions += 1
            if actual == "accept":
                auto_go_correct += 1
            else:
                auto_go_wrong += 1

    print(f"Backtest: {len(decided)} decided pairs\n")
    print(f"{'action':<16} {'accept':>7} {'clarify':>8} {'reject':>7} {'total':>6} {'A%':>5}")
    print("-" * 56)
    for act in ["auto_go", "ask_normally", "extra_caution"]:
        a, c, r = by_action[act]
        n = a + c + r
        if n == 0:
            print(f"{act:<16} {0:>7} {0:>8} {0:>7} {0:>6}   --")
            continue
        print(f"{act:<16} {a:>7} {c:>8} {r:>7} {n:>6} {a/n*100:>4.0f}%")

    if auto_go_decisions:
        prec = auto_go_correct / auto_go_decisions * 100
        print(f"\nauto_go precision: {auto_go_correct}/{auto_go_decisions} = {prec:.0f}%")
        print(f"auto_go coverage: {auto_go_decisions}/{len(decided)} = {auto_go_decisions/len(decided)*100:.0f}% of decided")
    else:
        print("\nNo auto_go decisions — threshold may be too high.")


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: sy_classifier.py <sy_text> | --eval | --json <obj>")
        sys.exit(1)

    if args[0] == "--eval":
        evaluate()
        return

    if args[0] == "--json":
        obj = json.loads(args[1])
        print(json.dumps(score_sy(obj.get("sy_text", ""), obj.get("scenario")), indent=2))
        return

    text = " ".join(args)
    print(json.dumps(score_sy(text), indent=2))


if __name__ == "__main__":
    main()

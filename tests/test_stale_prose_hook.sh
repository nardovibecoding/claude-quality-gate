#!/usr/bin/env bash
# test_stale_prose_hook.sh — 5-case fixture for stale-prose-hook.py
# Run: bash /Users/bernard/.claude/hooks/tests/test_stale_prose_hook.sh
# Exit 0 = all pass. Exit 1 = at least one failure.
set -euo pipefail

HOOK="python3 /Users/bernard/.claude/hooks/stale-prose-hook.py"
SKIPS_FILE="$HOME/.claude/scripts/state/stale-prose-skips.jsonl"
PASS=0
FAIL=0
ERRORS=()

assert_exit() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" -eq "$expected" ]; then
        echo "  PASS [$label] exit=$actual (expected $expected)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL [$label] exit=$actual (expected $expected)"
        FAIL=$((FAIL + 1))
        ERRORS+=("$label: expected exit $expected, got $actual")
    fi
}

assert_file_contains() {
    local label="$1" file="$2" pattern="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        echo "  PASS [$label] file contains '$pattern'"
        PASS=$((PASS + 1))
    else
        echo "  FAIL [$label] file does NOT contain '$pattern' in $file"
        FAIL=$((FAIL + 1))
        ERRORS+=("$label: pattern '$pattern' not found in $file")
    fi
}

make_hook_input() {
    local cmd="$1"
    printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(printf '%s' "$cmd" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
}

# ── Setup temp git repo ────────────────────────────────────────────────────
TMPDIR_BASE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

setup_repo() {
    local repo="$TMPDIR_BASE/repo_$1"
    mkdir -p "$repo"
    git -C "$repo" init -q
    git -C "$repo" config user.email "test@test.com"
    git -C "$repo" config user.name "Test"
    echo "$repo"
}

echo ""
echo "=== stale-prose-hook.py fixture tests ==="
echo ""

# ─────────────────────────────────────────────────────────────────────────
# CASE 1: BLOCK — config.json has _note mentioning thingX,
#          commit touches thingX.ts but NOT config.json
# ─────────────────────────────────────────────────────────────────────────
echo "--- CASE 1: BLOCK ---"
REPO1=$(setup_repo 1)

# Create and commit the initial prose file
cat > "$REPO1/config.json" <<'EOF'
{
  "_note": "thingXHandler is broken after the last refactor, needs review"
}
EOF
cat > "$REPO1/thingXHandler.ts" <<'EOF'
// initial version
export function thingXHandler() { return null; }
EOF
git -C "$REPO1" add .
git -C "$REPO1" commit -q -m "initial"

# Stage a change to thingXHandler.ts only (not config.json)
cat > "$REPO1/thingXHandler.ts" <<'EOF'
// fixed version
export function thingXHandler() { return 42; }
EOF
git -C "$REPO1" add thingXHandler.ts

# Run hook from repo dir
HOOK_INPUT=$(make_hook_input "git commit -m 'fix(thingXHandler): return 42'")
ACTUAL_EXIT=0
cd "$REPO1" && echo "$HOOK_INPUT" | $HOOK 2>/tmp/stale_hook_stderr.txt || ACTUAL_EXIT=$?
assert_exit "BLOCK" 2 "$ACTUAL_EXIT"
# Check stderr has blocking message
if grep -q "stale-prose-hook: BLOCKED" /tmp/stale_hook_stderr.txt 2>/dev/null; then
    echo "  PASS [BLOCK stderr] blocking message present"
    PASS=$((PASS + 1))
else
    echo "  FAIL [BLOCK stderr] no blocking message in stderr"
    FAIL=$((FAIL + 1))
    ERRORS+=("BLOCK stderr: no blocking message")
fi

# ─────────────────────────────────────────────────────────────────────────
# CASE 2: ALLOW — same setup but commit also touches config.json
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "--- CASE 2: ALLOW ---"
REPO2=$(setup_repo 2)

cat > "$REPO2/config.json" <<'EOF'
{
  "_note": "thingXHandler is broken after the last refactor, needs review"
}
EOF
cat > "$REPO2/thingXHandler.ts" <<'EOF'
export function thingXHandler() { return null; }
EOF
git -C "$REPO2" add .
git -C "$REPO2" commit -q -m "initial"

# Stage changes to BOTH files
cat > "$REPO2/thingXHandler.ts" <<'EOF'
export function thingXHandler() { return 42; }
EOF
cat > "$REPO2/config.json" <<'EOF'
{
  "_note": "thingXHandler fixed — returns 42 now"
}
EOF
git -C "$REPO2" add thingXHandler.ts config.json

HOOK_INPUT=$(make_hook_input "git commit -m 'fix(thingXHandler): return 42, update config note'")
ACTUAL_EXIT=0
cd "$REPO2" && echo "$HOOK_INPUT" | $HOOK 2>/dev/null || ACTUAL_EXIT=$?
assert_exit "ALLOW" 0 "$ACTUAL_EXIT"

# ─────────────────────────────────────────────────────────────────────────
# CASE 3: SKIP-MARKER — commit msg has [skip-stale-check=experimental]
#          → exit 0 + append to skips.jsonl
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "--- CASE 3: SKIP-MARKER ---"
REPO3=$(setup_repo 3)

cat > "$REPO3/config.json" <<'EOF'
{
  "_note": "thingXHandler is broken"
}
EOF
cat > "$REPO3/thingXHandler.ts" <<'EOF'
export function thingXHandler() { return null; }
EOF
git -C "$REPO3" add .
git -C "$REPO3" commit -q -m "initial"

cat > "$REPO3/thingXHandler.ts" <<'EOF'
export function thingXHandler() { return 42; }
EOF
git -C "$REPO3" add thingXHandler.ts

HOOK_INPUT=$(make_hook_input "git commit -m 'fix(thingXHandler): return 42 [skip-stale-check=experimental]'")
SKIP_COUNT_BEFORE=$(wc -l < "$SKIPS_FILE" 2>/dev/null || echo "0")
ACTUAL_EXIT=0
cd "$REPO3" && echo "$HOOK_INPUT" | $HOOK 2>/dev/null || ACTUAL_EXIT=$?
assert_exit "SKIP-MARKER exit" 0 "$ACTUAL_EXIT"

SKIP_COUNT_AFTER=$(wc -l < "$SKIPS_FILE" 2>/dev/null || echo "0")
if [ "$SKIP_COUNT_AFTER" -gt "$SKIP_COUNT_BEFORE" ]; then
    echo "  PASS [SKIP-MARKER log] skip appended to $SKIPS_FILE"
    PASS=$((PASS + 1))
else
    echo "  FAIL [SKIP-MARKER log] skip NOT logged (before=$SKIP_COUNT_BEFORE after=$SKIP_COUNT_AFTER)"
    FAIL=$((FAIL + 1))
    ERRORS+=("SKIP-MARKER log: no new entry in skips.jsonl")
fi
# Verify reason field
assert_file_contains "SKIP-MARKER reason" "$SKIPS_FILE" "experimental"

# ─────────────────────────────────────────────────────────────────────────
# CASE 4: NO-MATCH — commit touches symbol with no prose mentions
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "--- CASE 4: NO-MATCH ---"
REPO4=$(setup_repo 4)

cat > "$REPO4/config.json" <<'EOF'
{
  "_note": "unrelated widget needs attention"
}
EOF
cat > "$REPO4/zebra_parser.ts" <<'EOF'
export function zebra_parser() { return null; }
EOF
git -C "$REPO4" add .
git -C "$REPO4" commit -q -m "initial"

cat > "$REPO4/zebra_parser.ts" <<'EOF'
export function zebra_parser() { return 42; }
EOF
git -C "$REPO4" add zebra_parser.ts

HOOK_INPUT=$(make_hook_input "git commit -m 'fix(zebra_parser): return 42'")
ACTUAL_EXIT=0
cd "$REPO4" && echo "$HOOK_INPUT" | $HOOK 2>/dev/null || ACTUAL_EXIT=$?
assert_exit "NO-MATCH" 0 "$ACTUAL_EXIT"

# ─────────────────────────────────────────────────────────────────────────
# CASE 5: PERFORMANCE — 50 changed files → hook completes in <2s
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "--- CASE 5: PERFORMANCE ---"
REPO5=$(setup_repo 5)

# Create 50 source files + a config with a note
cat > "$REPO5/config.json" <<'EOF'
{
  "_note": "thingXHandler is broken"
}
EOF
for i in $(seq 1 50); do
    cat > "$REPO5/module_$i.ts" <<EOF
export function module_${i}_func() { return null; }
EOF
done
git -C "$REPO5" add .
git -C "$REPO5" commit -q -m "initial"

# Stage changes to all 50 files
for i in $(seq 1 50); do
    cat > "$REPO5/module_$i.ts" <<EOF
export function module_${i}_func() { return $i; }
EOF
done
git -C "$REPO5" add .

HOOK_INPUT=$(make_hook_input "git commit -m 'refactor: update all modules'")
T_START=$(python3 -c "import time; print(time.time())")
ACTUAL_EXIT=0
cd "$REPO5" && echo "$HOOK_INPUT" | $HOOK 2>/dev/null || ACTUAL_EXIT=0  # exit code doesn't matter for perf
T_END=$(python3 -c "import time; print(time.time())")
ELAPSED=$(python3 -c "print(round($T_END - $T_START, 2))")
ELAPSED_OK=$(python3 -c "print('yes' if $T_END - $T_START < 2.0 else 'no')")

if [ "$ELAPSED_OK" = "yes" ]; then
    echo "  PASS [PERFORMANCE] elapsed=${ELAPSED}s (<2s)"
    PASS=$((PASS + 1))
else
    echo "  FAIL [PERFORMANCE] elapsed=${ELAPSED}s (>=2s)"
    FAIL=$((FAIL + 1))
    ERRORS+=("PERFORMANCE: took ${ELAPSED}s, expected <2s")
fi

# ─────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────
echo ""
echo "=== SUMMARY ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "FAILURES:"
    for e in "${ERRORS[@]}"; do
        echo "  - $e"
    done
    exit 1
fi

echo ""
echo "All tests passed."
exit 0

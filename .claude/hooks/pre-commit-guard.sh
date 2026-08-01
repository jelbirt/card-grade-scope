#!/usr/bin/env bash
# PreToolUse guard for agent-made git commits in THIS repo.
# Contract: exit 0 allows; exit 2 blocks (stderr becomes the reason shown to
# the agent). Any other exit code silently allows, so every failure path here
# is deliberate.
#
# Rules enforced (escapes documented in CLAUDE.md, typed into the commit
# command itself so overrides are visible in the transcript):
#   1. scripts/checks.sh must pass in the worktree receiving the commit.
#      Escape: SKIP_CHECKS=1
#   2. No commits on main (PR-based flow). Escape: ALLOW_MAIN_COMMIT=1
#
# This is a guardrail for cooperating sessions, not a security boundary: it
# fails open on unreadable payloads, missing interpreters, or git errors so it
# never wedges unrelated work. But a command segment that won't tokenize falls
# back to a conservative substring match (multi-line commit messages tokenize
# badly and are the common case — skipping there would bypass the guard
# exactly when it matters).
set -uo pipefail

payload="$(cat 2>/dev/null)" || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

GUARD_REPO_COMMON="$(cd "$(dirname "$0")/../.." && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
export GUARD_REPO_COMMON

result="$(GUARD_PAYLOAD="$payload" python3 <<'PYEOF'
import json, os, shlex, subprocess, sys

def out(verdict, target=""):
    print(json.dumps({"verdict": verdict, "target": target}))
    sys.exit(0)

try:
    data = json.loads(os.environ.get("GUARD_PAYLOAD", ""))
    cmd = data.get("tool_input", {}).get("command", "")
except Exception:
    out("allow")
if not cmd or "git" not in cmd:
    out("allow")

OPS = {"&&", "||", ";", "|", "&"}

def split_segments(tokens):
    seg, segs = [], []
    for t in tokens:
        if t in OPS:
            if seg:
                segs.append(seg)
            seg = []
        else:
            seg.append(t)
    if seg:
        segs.append(seg)
    return segs

GIT_GLOBAL_FLAGS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace"}

def analyze(cmd_text, cwd):
    """Return (is_commit, commit_cwd, env_prefix) for the first git commit found."""
    try:
        tokens = shlex.split(cmd_text, posix=True)
    except ValueError:
        # Untokenizable (e.g. tricky quoting in a -m message): conservative
        # substring fallback — treat as a commit in the ambient cwd.
        if "git" in cmd_text and "commit" in cmd_text:
            return True, cwd, {}
        return False, cwd, {}
    for seg in split_segments(tokens):
        i, env, seg_cwd = 0, {}, cwd
        while i < len(seg):
            t = seg[i]
            if t == "env":
                i += 1
                continue
            if "=" in t and not t.startswith(("/", "-", ".")):
                k, _, v = t.partition("=")
                if k.isidentifier():
                    env[k] = v
                    i += 1
                    continue
            break
        if i >= len(seg):
            continue
        head = seg[i]
        if head == "cd" and i + 1 < len(seg):
            target = os.path.expanduser(seg[i + 1])
            cwd = os.path.normpath(os.path.join(cwd, target))
            continue
        if head in ("sh", "bash", "zsh") and "-c" in seg[i:]:
            ci = seg.index("-c", i)
            if ci + 1 < len(seg):
                r = analyze(seg[ci + 1], cwd)
                if r[0]:
                    return r
            continue
        if head == "eval":
            r = analyze(" ".join(seg[i + 1:]), cwd)
            if r[0]:
                return r
            continue
        if os.path.basename(head) != "git":
            continue
        j = i + 1
        git_cwd = cwd
        while j < len(seg) and seg[j].startswith("-"):
            if seg[j] == "-C" and j + 1 < len(seg):
                git_cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(seg[j + 1])))
                j += 2
            elif seg[j] in GIT_GLOBAL_FLAGS_WITH_ARG:
                j += 2
            else:
                j += 1
        if j < len(seg) and seg[j] == "commit":
            return True, git_cwd, env
    return False, cwd, {}

cwd = os.getcwd()
is_commit, target_cwd, env = analyze(cmd, cwd)
if not is_commit:
    out("allow")

# Scope to this repo by git common dir (worktree-proof).
try:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=target_cwd, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
except Exception:
    out("allow")
if not common or os.path.realpath(common) != os.path.realpath(os.environ.get("GUARD_REPO_COMMON", "")):
    out("allow")

# Full command text carries typed escapes even when they sit outside the
# parsed segment (e.g. "SKIP_CHECKS=1 git commit").
if "SKIP_CHECKS=1" in cmd or env.get("SKIP_CHECKS") == "1":
    skip_checks = True
else:
    skip_checks = False
allow_main = "ALLOW_MAIN_COMMIT=1" in cmd or env.get("ALLOW_MAIN_COMMIT") == "1"

try:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=target_cwd, capture_output=True, text=True, timeout=10,
    ).stdout.strip()
except Exception:
    out("allow")

if branch == "main" and not allow_main:
    out("block-main", target_cwd)
if skip_checks:
    out("allow")
out("run-checks", target_cwd)
PYEOF
)" || exit 0

verdict="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])' 2>/dev/null)" || exit 0
target="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["target"])' 2>/dev/null)" || exit 0

case "$verdict" in
  allow) exit 0 ;;
  block-main)
    echo "Blocked: direct commit to main. This repo uses PR-based flow (branch via scripts/new-worktree.sh). Deliberate override: prefix the commit with ALLOW_MAIN_COMMIT=1" >&2
    exit 2
    ;;
  run-checks)
    # Judge the tree being committed by its own checks.sh (branches may change the bar).
    checks="$target/scripts/checks.sh"
    [ -x "$checks" ] || exit 0
    if ! output="$("$checks" 2>&1)"; then
      echo "Blocked: scripts/checks.sh failed in $target — fix before committing (deliberate override: SKIP_CHECKS=1). Output tail:" >&2
      echo "$output" | tail -20 >&2
      exit 2
    fi
    exit 0
    ;;
  *) exit 0 ;;
esac

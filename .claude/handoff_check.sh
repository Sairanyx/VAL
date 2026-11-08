#!/usr/bin/env bash
# Stop hook: asks the agent to update its handoff if uncommitted files are newer than it.
# Exit 2 sends the message back to the agent. Prompts that change no files are not interrupted.

# Only ask once per stop, so the agent can't get stuck in a loop.
grep -q '"stop_hook_active": *true' && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

name=$(git config user.name | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
handoff="handoffs/${name:-unknown}.md"

changed=$({ git ls-files -m -o --exclude-standard; git diff --cached --name-only; } | sort -u)

while IFS= read -r file; do
    [ -n "$file" ] && [ -e "$file" ] || continue
    case "$file" in handoffs/*) continue ;; esac
    if [ ! -e "$handoff" ] || [ "$file" -nt "$handoff" ]; then
        echo "Files changed since the last handoff. Update $handoff (format in AGENTS.md)." >&2
        exit 2
    fi
done <<< "$changed"

exit 0

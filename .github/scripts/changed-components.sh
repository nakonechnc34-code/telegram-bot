#!/usr/bin/env bash
set -euo pipefail

python=true
attendance=true
browser=true
if [[ "$GITHUB_EVENT_NAME" == pull_request ]]; then
    git diff --no-renames --name-only -z "$BASE_SHA...$HEAD_SHA" > "$RUNNER_TEMP/wokker-changed-files"
    python=false
    attendance=false
    browser=false
    while IFS= read -r -d '' path; do
        case "$path" in
            docs/*.md|README.md|AGENTS.md) ;;
            frontend/*|tests/browser/*) browser=true ;;
            *) python=true; attendance=true; browser=true ;;
        esac
    done < "$RUNNER_TEMP/wokker-changed-files"
fi

printf 'python=%s\nattendance=%s\nbrowser=%s\n' "$python" "$attendance" "$browser" >> "$GITHUB_OUTPUT"

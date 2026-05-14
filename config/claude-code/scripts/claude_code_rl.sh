#!/usr/bin/env sh
set -eu

CLAUDE_BIN=${CLAUDE_CODE_BIN:-claude-js}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --claude-bin)
            if [ "$#" -lt 2 ]; then
                echo "Missing value for --claude-bin" >&2
                exit 2
            fi
            CLAUDE_BIN=$2
            shift 2
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

CLAUDE_CODE_WORKSPACE=${CLAUDE_CODE_WORKSPACE:-$(pwd)}
export CLAUDE_CODE_WORKSPACE

if [ -z "${CLAUDE_CODE_WORKSPACE_ID:-}" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
        CLAUDE_CODE_WORKSPACE_HASH=$(printf '%s' "$CLAUDE_CODE_WORKSPACE" | sha256sum | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        CLAUDE_CODE_WORKSPACE_HASH=$(printf '%s' "$CLAUDE_CODE_WORKSPACE" | shasum -a 256 | awk '{print $1}')
    elif command -v openssl >/dev/null 2>&1; then
        CLAUDE_CODE_WORKSPACE_HASH=$(printf '%s' "$CLAUDE_CODE_WORKSPACE" | openssl dgst -sha256 | awk '{print $NF}')
    else
        echo "sha256sum, shasum, or openssl is required to build CLAUDE_CODE_WORKSPACE_ID" >&2
        exit 2
    fi
    CLAUDE_CODE_WORKSPACE_ID=ws_$(printf '%s' "$CLAUDE_CODE_WORKSPACE_HASH" | cut -c 1-12)
fi
export CLAUDE_CODE_WORKSPACE_ID

if [ -z "${CLAUDE_CODE_RUN_ID:-}" ]; then
    CLAUDE_CODE_TIMESTAMP=$(date '+%H%M%S')
    CLAUDE_CODE_GUID=$$
    CLAUDE_CODE_RUN_ID=ccrun_${CLAUDE_CODE_WORKSPACE_ID}_${CLAUDE_CODE_TIMESTAMP}_${CLAUDE_CODE_GUID}
fi
export CLAUDE_CODE_RUN_ID

if [ -z "${CLAUDE_CODE_INSTANCE_ID:-}" ]; then
    CLAUDE_CODE_INSTANCE_ID=$(hostname 2>/dev/null || printf '%s' claude-code-default)
fi
if [ -z "$CLAUDE_CODE_INSTANCE_ID" ]; then
    CLAUDE_CODE_INSTANCE_ID=claude-code-default
fi
export CLAUDE_CODE_INSTANCE_ID

ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-http://127.0.0.1:8906/v1}
export ANTHROPIC_BASE_URL

CLAUDE_CODE_SESSION_EVENT_URL=${CLAUDE_CODE_SESSION_EVENT_URL:-http://127.0.0.1:8906/_agent/session-event}
export CLAUDE_CODE_SESSION_EVENT_URL

ANTHROPIC_CUSTOM_HEADERS="X-Agent-Name: claude-code
X-Agent-Run-Id: ${CLAUDE_CODE_RUN_ID}
X-Agent-Workspace-Id: ${CLAUDE_CODE_WORKSPACE_ID}
X-Agent-Workspace: ${CLAUDE_CODE_WORKSPACE}
X-Instance-Id: ${CLAUDE_CODE_INSTANCE_ID}"
export ANTHROPIC_CUSTOM_HEADERS

echo "Claude Code RL wrapper"
echo "  run_id:       ${CLAUDE_CODE_RUN_ID}"
echo "  workspace_id: ${CLAUDE_CODE_WORKSPACE_ID}"
echo "  workspace:    ${CLAUDE_CODE_WORKSPACE}"
echo "  base_url:     ${ANTHROPIC_BASE_URL}"

exec "$CLAUDE_BIN" "$@"

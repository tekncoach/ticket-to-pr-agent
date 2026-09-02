#!/usr/bin/env bash
#
# Smoke test for the hello-agent service.
#
# Prerequisites: the service must already be running with a real LLM key.
#   cp .env.example .env && $EDITOR .env      # paste your LLM_API_KEY
#   set -a && source .env && set +a
#   make run
#
# Then, from another terminal:
#   ./evals/tests.sh                          # defaults to http://127.0.0.1:8000
#   BASE_URL=http://host:port ./evals/tests.sh
#
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
CONTENT_TYPE="content-type: application/json"

pass=0
fail=0

# Pretty-print JSON when jq is available; otherwise print as-is.
pretty() {
  if command -v jq >/dev/null 2>&1; then jq .; else cat; fi
}

# check NAME EXPECTED_CODE  curl-args...
# Runs one request, compares the HTTP status, and prints the body.
check() {
  local name="$1" expected="$2"
  shift 2
  local response code body
  response="$(curl -s -w $'\n%{http_code}' "$@")"
  code="${response##*$'\n'}"
  body="${response%$'\n'*}"

  if [[ "$code" == "$expected" ]]; then
    printf '\xe2\x9c\x93 %-30s [%s]\n' "$name" "$code"
    pass=$((pass + 1))
  else
    printf '\xe2\x9c\x97 %-30s [got %s, want %s]\n' "$name" "$code" "$expected"
    fail=$((fail + 1))
  fi
  printf '%s\n\n' "$body" | pretty
}

echo "hello-agent smoke test -> $BASE_URL"
echo

# Preflight: fail fast with a clear message if the service is unreachable.
if ! curl -s -o /dev/null "$BASE_URL/health"; then
  echo "Cannot reach $BASE_URL — start the service first (make run)." >&2
  exit 1
fi

# 1. Healthcheck — needs no LLM key.
check "GET /health" 200 "$BASE_URL/health"

# 2. Chat that should make the agent call the get_time tool.
check "POST /v1/chat (Paris time)" 200 \
  "$BASE_URL/v1/chat" -H "$CONTENT_TYPE" \
  -d '{"message":"What time is it in Paris?"}'

echo "----"
echo "passed: $pass   failed: $fail"
[[ "$fail" -eq 0 ]]

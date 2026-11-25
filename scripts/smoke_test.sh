#!/usr/bin/env bash
# Contract smoke test against a running backend (local or deployed).
#   ./scripts/smoke_test.sh http://localhost:8000
#   ./scripts/smoke_test.sh https://your-backend.onrender.com
# Needs: bash, curl, python3. Uses ~6 real LLM calls.
set -uo pipefail
API="${1:-http://localhost:8000}"
API="${API%/}"
RUN="$(date +%s)-$RANDOM"
PASS=0; FAIL=0
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
json() { python3 -c "import json,sys; d=json.load(open('$1')); print(eval('d'+sys.argv[1]))" "$2" 2>/dev/null; }

# post <outfile> <json-body> [simulate-header]  -> prints HTTP status
post() {
  local extra=()
  [ -n "${3:-}" ] && extra=(-H "X-Simulate-Failure: $3")
  curl -s -o "$1" -w '%{http_code}' -X POST "$API/chat" -H 'Content-Type: application/json' ${extra[@]+"${extra[@]}"} --data "$2"
}

echo "Smoke testing $API"

code=$(curl -s -o "$TMP/h" -w '%{http_code}' "$API/health")
[ "$code" = 200 ] && [ "$(json "$TMP/h" "['status']")" = ok ] \
  && ok "GET /health -> 200 ($(cat "$TMP/h"))" || bad "GET /health" "$code $(cat "$TMP/h" 2>/dev/null)"

MSG="What is the capital of France? (smoke $RUN)"
code=$(post "$TMP/c1" "{\"session_id\":\"smoke-a-$RUN\",\"message\":\"$MSG\"}")
[ "$code" = 200 ] && [ "$(json "$TMP/c1" "['metadata']['resolution_source']")" = LIVE_INFERENCE ] \
  && ok "POST /chat first message -> LIVE_INFERENCE via $(json "$TMP/c1" "['metadata']['key_id']") ($(json "$TMP/c1" "['metadata']['latency_ms']") ms)" \
  || bad "POST /chat live" "$code $(cat "$TMP/c1")"

code=$(post "$TMP/c2" "{\"session_id\":\"smoke-b-$RUN\",\"message\":\"$MSG\"}")
if [ "$code" = 200 ] && [ "$(json "$TMP/c2" "['metadata']['resolution_source']")" = LLM_CACHE ] \
   && [ "$(json "$TMP/c1" "['reply']")" = "$(json "$TMP/c2" "['reply']")" ] \
   && [ "$(json "$TMP/c2" "['metadata']['key_id']")" = None ]; then
  ok "same first message, new session -> LLM_CACHE, identical reply ($(json "$TMP/c2" "['metadata']['latency_ms']") ms)"
else bad "cache hit" "$code $(cat "$TMP/c2")"; fi

code=$(post "$TMP/c3" "{\"session_id\":\"smoke-a-$RUN\",\"message\":\"And what is its population, roughly?\"}")
[ "$code" = 200 ] && ok "multi-turn follow-up -> $(json "$TMP/c3" "['metadata']['resolution_source']"), input_tokens=$(json "$TMP/c3" "['metadata']['input_tokens']")" \
  || bad "multi-turn" "$code $(cat "$TMP/c3")"

code=$(curl -s -o "$TMP/hist" -w '%{http_code}' "$API/sessions/smoke-a-$RUN/messages")
n=$(json "$TMP/hist" "['messages'].__len__()")
[ "$code" = 200 ] && [ "$n" = 4 ] && ok "GET /sessions/{id}/messages -> 4 messages, oldest first" || bad "history" "$code $(cat "$TMP/hist")"

code=$(post "$TMP/f1" "{\"session_id\":\"smoke-c-$RUN\",\"message\":\"Say hello (failover $RUN)\"}" "key_1=429")
[ "$code" = 200 ] && [ "$(json "$TMP/f1" "['metadata']['key_id']")" = key_2 ] \
  && ok "X-Simulate-Failure: key_1=429 -> 200 from key_2, fallback_attempts=$(json "$TMP/f1" "['metadata']['fallback_attempts']")" \
  || bad "failover key_1=429 (is ENABLE_FAILURE_SIMULATION=true?)" "$code $(cat "$TMP/f1")"

code=$(post "$TMP/f2" "{\"session_id\":\"smoke-d-$RUN\",\"message\":\"Say hi (all fail $RUN)\"}" "*=429")
[ "$code" = 503 ] && [ "$(json "$TMP/f2" "['detail']")" = "all providers unavailable" ] \
  && ok "X-Simulate-Failure: *=429 -> 503 all providers unavailable" || bad "all keys fail" "$code $(cat "$TMP/f2")"
code=$(curl -s -o /dev/null -w '%{http_code}' "$API/sessions/smoke-d-$RUN/messages")
[ "$code" = 404 ] && ok "failed request not added to history (404)" || bad "503 must not be saved" "$code"

code=$(post "$TMP/v1" "{\"session_id\":\"smoke-e-$RUN\",\"message\":\"   \"}")
[ "$code" = 422 ] && ok "blank message -> 422" || bad "blank message" "$code"
long=$(python3 -c "print('a'*4001)")
code=$(post "$TMP/v2" "{\"session_id\":\"smoke-e-$RUN\",\"message\":\"$long\"}")
[ "$code" = 422 ] && ok "4001-char message -> 422" || bad "long message" "$code"
code=$(post "$TMP/v3" '{"session_id": "x", "message": ')
[ "$code" = 422 ] && ok "malformed JSON -> 422" || bad "malformed JSON" "$code"
code=$(curl -s -o "$TMP/nf" -w '%{http_code}' "$API/sessions/never-seen-$RUN/messages")
[ "$code" = 404 ] && [ "$(json "$TMP/nf" "['detail']")" = "session not found" ] && ok "unknown session -> 404" || bad "unknown session" "$code"

echo ""
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]

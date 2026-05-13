#!/usr/bin/env bash
# Headless test of msf-ui — drives every UI flow over HTTP.
set -euo pipefail
BASE="http://localhost:8080"

pass=0; fail=0
check() {
  local label="$1"; shift
  local cmd="$*"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "  PASS  $label"
    pass=$((pass + 1))
  else
    echo "  FAIL  $label  ($cmd)"
    fail=$((fail + 1))
  fi
}

echo "== UI — HTML page loads =="
check "GET / returns 200 and contains expected element ids" \
  "curl -sf $BASE/ | grep -q '#template-list\\|template-list'"
check "GET /static/app.js is served"     "curl -sf $BASE/static/app.js   | head -c20 | grep -q ''"
check "GET /static/style.css is served"  "curl -sf $BASE/static/style.css | head -c20 | grep -q ''"

echo
echo "== Backend API =="
check "GET /api/health"     "curl -sf $BASE/api/health"
check "GET /api/templates returns 9 entries" \
  "[ \$(curl -sf $BASE/api/templates | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))') -eq 9 ]"

echo
echo "== Validation toggle =="
echo "-- valid template, validate-only --"
curl -sf -X POST -H 'Content-Type: application/json' -d '{
  "node_id":"11111111-1111-1111-1111-111111111111",
  "template_name":"registration"
}' $BASE/api/validate | python3 -m json.tool

echo "-- intentionally bad template (icd_version with underscores), validate-only --"
BAD_REG=$(curl -sf $BASE/api/templates/registration | python3 -c "import json,sys;print(json.load(sys.stdin)['raw'])" \
  | python3 -c "import sys; print(sys.stdin.read().replace('BSI Flex 335 v2.0', 'BSI_Flex_335_v2.0'))")
curl -sf -X POST -H 'Content-Type: application/json' -d "$(python3 -c "
import json
print(json.dumps({'node_id':'11111111-1111-1111-1111-111111111111','raw_json': '''$BAD_REG'''}))
")" $BASE/api/validate | python3 -m json.tool

echo
echo "== NTP probe =="
curl -sf "$BASE/api/ntp?timeout=2" | python3 -m json.tool

echo
echo "== Round-trip every template against a local stub =="
# start the stub
/home/ubuntu20/ws/multi-sensor-fusion/deprecated/compat-baseline/edge-sim/.venv/bin/python - <<'PY' &
import asyncio, struct, sys, os
sys.path.insert(0, '/home/ubuntu20/ws/multi-sensor-fusion/deprecated/compat-baseline/edge-sim')
os.chdir('/home/ubuntu20/ws/multi-sensor-fusion/deprecated/compat-baseline/edge-sim')
from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as m

async def handle(reader, writer):
    while True:
        try:
            hdr = await reader.readexactly(4)
        except asyncio.IncompleteReadError:
            return
        (n,) = struct.unpack('<I', hdr)
        body = await reader.readexactly(n)
        req = m.SapientMessage(); req.ParseFromString(body)
        ack = m.SapientMessage()
        ack.timestamp.GetCurrentTime()
        ack.node_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        ack.destination_id = req.node_id
        ack.registration_ack.acceptance = True
        out = ack.SerializeToString()
        writer.write(struct.pack('<I', len(out)) + out)
        await writer.drain()

async def main():
    srv = await asyncio.start_server(handle, '127.0.0.1', 14002)
    async with srv:
        await srv.serve_forever()
asyncio.run(main())
PY
STUB_PID=$!
sleep 1

UUID=$(python3 -c "import uuid;print(uuid.uuid4())")
for tpl in registration registration_ack status_report detection_report task task_ack alert alert_ack error; do
  result=$(curl -sf -X POST -H 'Content-Type: application/json' -d "{
    \"host\":\"127.0.0.1\",\"port\":14002,\"node_id\":\"$UUID\",
    \"template_name\":\"$tpl\",\"recv_timeout_s\":1,\"drain_after_s\":0.3,
    \"validate_before_send\":true
  }" $BASE/api/send)
  ok=$(echo "$result" | python3 -c "import json,sys;r=json.load(sys.stdin);print('OK' if (not r.get('error') and any(t['direction']=='recv' for t in r['transcript'])) else 'FAIL', r.get('error',''))" )
  echo "  send $tpl :: $ok"
done

kill "$STUB_PID" 2>/dev/null || true
wait "$STUB_PID" 2>/dev/null || true

echo
echo "== Recent runs =="
curl -sf $BASE/api/runs | python3 -c "
import json,sys
runs = json.load(sys.stdin)
print(f'{len(runs)} runs total; last 9:')
for r in runs[:9]:
    print(f'  {r[\"run_id\"]}  {r[\"template\"]:20s}  {r[\"host\"]}:{r[\"port\"]}  recv={r[\"n_received\"]}  err={r[\"error\"]}')"

echo
echo "PASS=$pass  FAIL=$fail"
[[ $fail -eq 0 ]]

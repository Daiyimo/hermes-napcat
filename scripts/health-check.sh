#!/usr/bin/env bash
# hermes-napcat 快速健康检查
# 适合作为 cron 任务或用 systemd timer 定期执行
# 用法: bash scripts/health-check.sh [--json]

set -e

# Detect python
PYTHON=""
for cmd in $PYTHON python $PYTHON.12 $PYTHON.11; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$cmd"; break
    fi
done
[ -n "$PYTHON" ] || { echo "错误: 未找到 Python"; exit 1; }

HTTP_URL=$($PYTHON -c "import os; print(os.getenv('NAPCAT_HTTP_URL', ''))" 2>/dev/null || echo "")
TOKEN=$($PYTHON -c "import os; print(os.getenv('NAPCAT_TOKEN', ''))" 2>/dev/null || echo "")
WS_URL=$($PYTHON -c "import os; print(os.getenv('NAPCAT_WS_URL', ''))" 2>/dev/null || echo "")

OUTPUT_JSON=false
[ "$1" = "--json" ] && OUTPUT_JSON=true

check_http() {
    $PYTHON -c "
import httpx, os, asyncio, json
async def go():
    token = os.getenv('NAPCAT_TOKEN', '')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post('${HTTP_URL}/get_login_info', json={}, headers=headers)
            if r.status_code == 200 and r.json().get('retcode') == 0:
                d = r.json().get('data', {})
                return 'ok', d.get('user_id', '?'), d.get('nickname', '?')
            return 'fail', 0, r.text[:100]
    except Exception as e:
        return 'error', 0, str(e)
print(json.dumps(asyncio.run(go())))
" 2>/dev/null || echo '["error",0,"python failed"]'
}

check_ws() {
    $PYTHON -c "
import asyncio, websockets.client, os, json
async def go():
    headers = {}
    token = os.getenv('NAPCAT_TOKEN', '')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        ws = await websockets.client.connect('${WS_URL}', extra_headers=headers, open_timeout=5)
        await ws.close()
        return 'ok'
    except Exception as e:
        return str(e)
print(json.dumps(asyncio.run(go())))
" 2>/dev/null || echo '"python failed"'
}

# HTTP check
HTTP_RESULT=$(check_http)
HTTP_STATUS=$(echo "$HTTP_RESULT" | $PYTHON -c "import sys,json; a=json.loads(sys.stdin.read()); print(a[0])" 2>/dev/null || echo "error")

# WS check (only if URL is set)
WS_STATUS="skipped"
if [ -n "$WS_URL" ]; then
    WS_STATUS=$(check_ws)
    WS_STATUS=$(echo "$WS_STATUS" | $PYTHON -c "import sys; s=sys.stdin.read().strip().strip('\"'); print('ok' if s=='ok' else 'fail')" 2>/dev/null || echo "fail")
fi

if $OUTPUT_JSON; then
    $PYTHON -c "
import json
print(json.dumps({
    'http': '${HTTP_STATUS}',
    'ws': '${WS_STATUS}',
    'url': '${HTTP_URL}'
}))
"
else
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

    if [ "$HTTP_STATUS" = "ok" ]; then
        QQ=$(echo "$HTTP_RESULT" | $PYTHON -c "import sys,json; print(json.loads(sys.stdin.read())[1])" 2>/dev/null)
        NICK=$(echo "$HTTP_RESULT" | $PYTHON -c "import sys,json; print(json.loads(sys.stdin.read())[2])" 2>/dev/null)
        echo -e "${GREEN}✓${NC} NapCat 在线 — $NICK ($QQ)"
    else
        ERR=$(echo "$HTTP_RESULT" | $PYTHON -c "import sys,json; print(json.loads(sys.stdin.read())[2])" 2>/dev/null || echo "unknown")
        echo -e "${RED}✗${NC} NapCat HTTP 离线 — $ERR"
    fi

    [ "$WS_STATUS" = "ok" ] && echo -e "${GREEN}✓${NC} WebSocket 正常" || echo -e "${YELLOW}!${NC} WebSocket: $WS_STATUS"
fi

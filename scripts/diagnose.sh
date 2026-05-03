#!/usr/bin/env bash
# hermes-napcat 诊断工具
# 检查 NapCat 适配器的所有依赖、配置和连通性
# 用法: bash scripts/diagnose.sh

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
section() { echo -e "\n${CYAN}── $* ──${NC}"; }

# Detect python binary (try $PYTHON, then python)
PYTHON=""
for cmd in $PYTHON python $PYTHON.12 $PYTHON.11; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$cmd"; break
    fi
done
if [ -z "$PYTHON" ]; then
    echo -e "${RED}错误: 未找到 Python${NC}"
    exit 1
fi

# ── 环境变量 ──────────────────────────────────────────────────
section "1. 环境变量检查"

check_env() {
    local val=$($PYTHON -c "import os; print(os.getenv('$1', ''))" 2>/dev/null || echo "")
    if [ -n "$val" ]; then
        pass "$1 = $val"
    else
        fail "$1 未设置"
    fi
}

check_env "NAPCAT_HTTP_URL"
check_env "NAPCAT_WS_URL"

NAPCAT_TOKEN=$($PYTHON -c "import os; print(os.getenv('NAPCAT_TOKEN', ''))" 2>/dev/null || echo "")
if [ -n "$NAPCAT_TOKEN" ]; then
    pass "NAPCAT_TOKEN = ***${NAPCAT_TOKEN: -3}"
else
    warn "NAPCAT_TOKEN 未设置（未启用鉴权）"
fi

ADMIN_USERS=$($PYTHON -c "import os; print(os.getenv('NAPCAT_ADMIN_USERS', ''))" 2>/dev/null || echo "")
if [ -n "$ADMIN_USERS" ]; then
    pass "NAPCAT_ADMIN_USERS = $ADMIN_USERS"
else
    warn "NAPCAT_ADMIN_USERS 未设置（无管理员）"
fi

ALLOWED=$($PYTHON -c "import os; print(os.getenv('NAPCAT_ALLOWED_USERS', ''))" 2>/dev/null || echo "")
ALLOW_ALL=$($PYTHON -c "import os; print(os.getenv('NAPCAT_ALLOW_ALL_USERS', ''))" 2>/dev/null || echo "")
if [ "$ALLOW_ALL" = "true" ]; then
    warn "开放访问模式（NAPCAT_ALLOW_ALL_USERS=true）"
elif [ -n "$ALLOWED" ]; then
    pass "NAPCAT_ALLOWED_USERS = $ALLOWED"
else
    fail "未设置白名单且未启用开放访问 — 所有用户将被拒绝"
fi

# ── Python 依赖 ───────────────────────────────────────────────
section "2. Python 依赖检查"

check_python_pkg() {
    if $PYTHON -c "import $1" 2>/dev/null; then
        pass "$1 已安装"
    else
        fail "$1 未安装 — pip install $1"
    fi
}

check_python_pkg "websockets"
check_python_pkg "httpx"

# ── HTTP API 连通性 ──────────────────────────────────────────
section "3. NapCat HTTP API 连通性"

HTTP_URL=$($PYTHON -c "import os; print(os.getenv('NAPCAT_HTTP_URL', ''))" 2>/dev/null || echo "")

if [ -z "$HTTP_URL" ]; then
    fail "NAPCAT_HTTP_URL 未设置，跳过 HTTP 检查"
else
    # 3.1 基本连通性
    echo -n "  HTTP Ping: $HTTP_URL ... "
    if $PYTHON -c "
import httpx, asyncio
async def check():
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get('${HTTP_URL}/get_login_info')
            return r.status_code == 200
    except:
        return False
print('OK' if asyncio.run(check()) else 'FAIL')
" 2>/dev/null | grep -q "OK"; then
        pass "HTTP API 可达"
    else
        fail "HTTP API 不可达 — 检查 NapCat 是否已启动"
    fi

    # 3.2 获取登录信息
    echo -n "  获取机器人信息 ... "
    LOGIN_INFO=$($PYTHON -c "
import httpx, asyncio, json, os
async def go():
    token = os.getenv('NAPCAT_TOKEN', '')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post('${HTTP_URL}/get_login_info', json={}, headers=headers)
            return r.text
    except Exception as e:
        return json.dumps({'error': str(e)})
print(asyncio.run(go()))
" 2>/dev/null || echo '{"error": "python script failed"}')

    if echo "$LOGIN_INFO" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('nickname',''))" 2>/dev/null | grep -q .; then
        NICK=$(echo "$LOGIN_INFO" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('nickname',''))" 2>/dev/null)
        QQ=$(echo "$LOGIN_INFO" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('user_id',''))" 2>/dev/null)
        pass "已登录: $NICK (QQ: $QQ)"
    else
        fail "无法获取机器人信息: $(echo "$LOGIN_INFO" | head -c 200)"
    fi
fi

# ── WebSocket 连通性 ─────────────────────────────────────────
section "4. NapCat WebSocket 连通性"

WS_URL=$($PYTHON -c "import os; print(os.getenv('NAPCAT_WS_URL', ''))" 2>/dev/null || echo "")

if [ -z "$WS_URL" ]; then
    fail "NAPCAT_WS_URL 未设置，跳过 WS 检查"
else
    echo -n "  WS 连接测试: $WS_URL ... "
    if $PYTHON -c "
import asyncio, websockets.client, os
async def check():
    try:
        headers = {}
        token = os.getenv('NAPCAT_TOKEN', '')
        if token:
            headers['Authorization'] = f'Bearer {token}'
        ws = await websockets.client.connect('${WS_URL}', additional_headers=headers, open_timeout=5)
        await ws.close()
        return True
    except:
        return False
print('OK' if asyncio.run(check()) else 'FAIL')
" 2>/dev/null | grep -q "OK"; then
        pass "WebSocket 已连接"
    else
        fail "WebSocket 不可达 — 检查 NapCat WS Server 是否已启用"
    fi
fi

# ── Hermes 集成检查 ──────────────────────────────────────────
section "5. Hermes Agent 集成检查"

HERMES_HOME=$($PYTHON -c "
import importlib.util, os
spec = importlib.util.find_spec('hermes_cli')
if spec:
    print(os.path.dirname(os.path.dirname(spec.origin)))
" 2>/dev/null || echo "")

if [ -n "$HERMES_HOME" ]; then
    pass "hermes_cli 已安装: $HERMES_HOME"

    GATEWAY_PY="$HERMES_HOME/hermes_cli/gateway.py"
    if grep -q '"key": "napcat"' "$GATEWAY_PY" 2>/dev/null; then
        pass "gateway.py 包含 NapCat 条目"
    else
        warn "gateway.py 缺少 NapCat 条目 — 运行 install.sh 修补"
    fi

    PLATFORM_DIR="$HERMES_HOME/gateway/platforms/napcat"
    if [ -f "$PLATFORM_DIR/adapter.py" ]; then
        pass "适配器已安装: $PLATFORM_DIR"
    else
        fail "适配器未安装到 $PLATFORM_DIR"
    fi
else
    warn "未检测到 hermes_cli — 可能未安装 Hermes Agent"
fi

# ── 总结 ──────────────────────────────────────────────────────
section "6. 总结"
echo ""
echo "  如有失败项，参考 README.md 故障排查章节"
echo "  快速配置: hermes gateway setup"
echo "  启动服务: hermes gateway"
echo ""

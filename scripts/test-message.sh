#!/usr/bin/env bash
# hermes-napcat 测试消息发送
# 直接调用 NapCat HTTP API 发送消息，不经过 Hermes Agent
# 用法:
#   bash scripts/test-message.sh 123456789 "你好"            # 私聊
#   bash scripts/test-message.sh g:987654321 "大家好"        # 群聊 (g:前缀)
#   bash scripts/test-message.sh 123456789 "图片测试" image  # 带图片
#   bash scripts/test-message.sh                            # 交互模式

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

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

send_msg() {
    local target="$1"
    local text="$2"
    local media_type="${3:-text}"

    local payload
    if [[ "$target" == g:* ]]; then
        local gid="${target#g:}"
        payload=$($PYTHON -c "
import json
print(json.dumps({
    'message_type': 'group',
    'group_id': int($gid),
    'message': [{'type': 'text', 'data': {'text': '${text}'}}]
}))
" 2>/dev/null)
        echo -e "${CYAN}发送群聊消息 → 群 $gid${NC}"
    else
        payload=$($PYTHON -c "
import json
print(json.dumps({
    'message_type': 'private',
    'user_id': int($target),
    'message': [{'type': 'text', 'data': {'text': '${text}'}}]
}))
" 2>/dev/null)
        echo -e "${CYAN}发送私聊消息 → QQ $target${NC}"
    fi

    $PYTHON -c "
import httpx, os, json, asyncio
async def go():
    headers = {'Content-Type': 'application/json'}
    token = '${TOKEN}'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post('${HTTP_URL}/send_msg', content='''${payload}''', headers=headers)
        resp = r.json()
        if resp.get('retcode') == 0:
            mid = resp.get('data', {}).get('message_id', '?')
            print(f'  \033[0;32m✓ 发送成功 (message_id={mid})\033[0m')
        else:
            print(f'  \033[0;31m✗ 发送失败: {resp.get(\"wording\", resp.get(\"message\", \"unknown\"))}\033[0m')
asyncio.run(go())
" 2>/dev/null || echo -e "  ${RED}✗ Python 执行失败${NC}"
}

# ── 主逻辑 ────────────────────────────────────────────────────
if [ -z "$HTTP_URL" ]; then
    echo -e "${RED}错误: NAPCAT_HTTP_URL 未设置${NC}"
    echo "  先运行 scripts/quick-setup-env.sh 配置环境变量"
    exit 1
fi

echo -e "${GREEN}NapCat HTTP: $HTTP_URL${NC}"

if [ $# -ge 2 ]; then
    # 命令行模式
    send_msg "$1" "$2" "${3:-text}"
elif [ $# -eq 1 ] && [ "$1" != "-h" ] && [ "$1" != "--help" ]; then
    echo "用法: bash scripts/test-message.sh <QQ号或g:群号> <消息内容>"
    exit 1
elif [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "用法:"
    echo "  bash scripts/test-message.sh 123456789 \"消息\"    私聊"
    echo "  bash scripts/test-message.sh g:123456789 \"消息\"  群聊"
    echo "  bash scripts/test-message.sh                    交互模式"
    exit 0
else
    # 交互模式
    read -r -p "$(echo -e "${CYAN}目标 (QQ号 或 g:群号)${NC}: ")" target
    [ -z "$target" ] && { echo "取消"; exit 0; }
    read -r -p "$(echo -e "${CYAN}消息内容${NC}: ")" text
    [ -z "$text" ] && { echo "取消"; exit 0; }
    echo ""
    send_msg "$target" "$text"
fi

#!/usr/bin/env bash
# hermes-napcat 快速环境变量配置
# 直接编辑 .env 文件（不依赖 hermes gateway setup）
# 用法: bash scripts/quick-setup-env.sh [hermes_home]

set -e

HERMES_HOME="${1:-/opt/hermes}"

if [ ! -d "$HERMES_HOME" ]; then
    echo "错误: 目录不存在: $HERMES_HOME"
    echo "用法: bash scripts/quick-setup-env.sh /path/to/hermes"
    exit 1
fi

ENV_FILE="$HERMES_HOME/.env"
[ -f "$ENV_FILE" ] && echo "  ✓ 找到 .env: $ENV_FILE" || echo "  .env 不存在，将创建: $ENV_FILE"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

read_input() {
    local prompt="$1"
    local default="$2"
    if [ -n "$default" ]; then
        read -r -p "$(echo -e "${CYAN}${prompt}${NC} [${default}]: ")" val
        echo "${val:-$default}"
    else
        read -r -p "$(echo -e "${CYAN}${prompt}${NC}: ")" val
        echo "$val"
    fi
}

set_env() {
    local key="$1"; local val="$2"
    val=$(echo "$val" | sed 's/[&/\]/\\&/g')
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s/^${key}=.*/${key}=${val}/" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
    echo -e "  ${GREEN}✓${NC} ${key}=${val}"
}

echo ""
echo -e "${YELLOW}── hermes-napcat 快速配置 ──${NC}"
echo ""

HTTP_URL=$(read_input "NapCat HTTP API 地址 (例: http://127.0.0.1:3000)" "${NAPCAT_HTTP_URL:-}")
[ -n "$HTTP_URL" ] && set_env "NAPCAT_HTTP_URL" "$HTTP_URL"

WS_URL=$(read_input "NapCat WebSocket 地址 (例: ws://127.0.0.1:3001)" "${NAPCAT_WS_URL:-}")
[ -n "$WS_URL" ] && set_env "NAPCAT_WS_URL" "$WS_URL"

TOKEN=$(read_input "访问令牌 (可选，无 token 留空)" "")
[ -n "$TOKEN" ] && set_env "NAPCAT_TOKEN" "$TOKEN" || echo "  跳过 Token"

ALLOWED=$(read_input "允许私聊的 QQ 号 (逗号分隔，留空=所有人)" "")
if [ -n "$ALLOWED" ]; then
    set_env "NAPCAT_ALLOWED_USERS" "$(echo "$ALLOWED" | tr -d ' ')"
else
    read -r -p "$(echo -e "${CYAN}开放访问? (y/N)${NC}: ")" open
    if [ "$open" = "y" ] || [ "$open" = "Y" ]; then
        set_env "NAPCAT_ALLOW_ALL_USERS" "true"
    fi
fi

GROUP_ALLOWED=$(read_input "允许群聊的 QQ 号 (逗号分隔，留空=不限制)" "")
[ -n "$GROUP_ALLOWED" ] && set_env "NAPCAT_GROUP_ALLOWED_USERS" "$(echo "$GROUP_ALLOWED" | tr -d ' ')" || echo "  跳过群聊白名单"

ADMINS=$(read_input "管理员 QQ 号 (逗号分隔，留空跳过)" "")
[ -n "$ADMINS" ] && set_env "NAPCAT_ADMIN_USERS" "$(echo "$ADMINS" | tr -d ' ')" || echo "  跳过管理员"

HOME_CH=$(read_input "默认投递目标 (QQ号 或 g:群号，留空跳过)" "")
[ -n "$HOME_CH" ] && set_env "NAPCAT_HOME_CHANNEL" "$HOME_CH" || echo "  跳过默认投递目标"

echo ""
echo -e "${GREEN}配置完成！${NC}"
echo "  运行 hermes gateway 启动服务"
echo "  或运行 scripts/diagnose.sh 验证配置"

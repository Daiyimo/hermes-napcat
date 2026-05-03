#!/usr/bin/env bash
# hermes-napcat 日志查看工具
# 实时查看 Hermes Gateway 日志，高亮 NapCat 相关条目
# 用法:
#   bash scripts/logs-tail.sh              # 实时跟踪
#   bash scripts/logs-tail.sh -n 100       # 最近 100 行
#   bash scripts/logs-tail.sh --grep WS    # 过滤 WebSocket 相关日志

HERMES_HOME="${HERMES_HOME:-/opt/hermes}"
LOG_DIR="$HERMES_HOME/logs"

N_LINES=50
GREP_PATTERN=""

while [ $# -gt 0 ]; do
    case "$1" in
        -n) N_LINES="$2"; shift 2 ;;
        --grep) GREP_PATTERN="$2"; shift 2 ;;
        -h|--help)
            echo "用法: bash scripts/logs-tail.sh [-n N] [--grep PATTERN]"
            exit 0
            ;;
        *) shift ;;
    esac
done

find_log() {
    for f in "$LOG_DIR/gateway.log" "$LOG_DIR/hermes.log" "$LOG_DIR/hermes-agent.log" /tmp/hermes*.log; do
        [ -f "$f" ] && echo "$f" && return
    done
    echo ""
}

LOG_FILE=$(find_log)

if [ -z "$LOG_FILE" ]; then
    echo "未找到日志文件，尝试的路径:"
    echo "  $LOG_DIR/gateway.log"
    echo "  $LOG_DIR/hermes.log"
    echo "  /tmp/hermes*.log"
    echo ""
    echo "可设置 HERMES_HOME 环境变量指定目录"
    exit 1
fi

YELLOW='\033[1;33m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'

echo -e "${CYAN}日志文件: $LOG_FILE${NC}"

if [ -n "$GREP_PATTERN" ]; then
    tail -n "$N_LINES" -f "$LOG_FILE" 2>/dev/null | grep --color=always -i "$GREP_PATTERN"
else
    tail -n "$N_LINES" -f "$LOG_FILE" 2>/dev/null | while IFS= read -r line; do
        if echo "$line" | grep -qi "napcat\|onebot\|qq"; then
            echo -e "${YELLOW}$line${NC}"
        elif echo "$line" | grep -qi "error\|exception\|traceback\|fatal"; then
            echo -e "${MAGENTA}$line${NC}"
        else
            echo "$line"
        fi
    done
fi

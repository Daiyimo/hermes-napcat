#!/usr/bin/env bash
# hermes-napcat install script
# 用法：
#   bash install.sh              # 自动检测 hermes 安装目录
#   bash install.sh /opt/hermes  # 手动指定 hermes 安装目录

set -e

REPO_URL="https://github.com/Daiyimo/hermes-napcat.git"
PROXY_REPO_URL="https://gh-proxy.com/https://github.com/Daiyimo/hermes-napcat.git"

# ── 颜色输出 ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[hermes-napcat]${NC} $*"; }
success() { echo -e "${GREEN}[hermes-napcat]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[hermes-napcat]${NC} ! $*"; }
error()   { echo -e "${RED}[hermes-napcat]${NC} ✗ $*"; exit 1; }

# ── 定位 hermes 安装目录 ──────────────────────────────────────
find_hermes_home() {
    if [ -n "$1" ] && [ -f "$1/hermes_cli/gateway.py" ]; then
        echo "$1"; return
    fi
    for candidate in /opt/hermes /opt/hermes-agent "$HOME/.hermes" "$HOME/hermes-agent"; do
        if [ -f "$candidate/hermes_cli/gateway.py" ]; then
            echo "$candidate"; return
        fi
    done
    # 从 Python 包路径反推
    python3 -c "
import importlib.util, os, sys
spec = importlib.util.find_spec('hermes_cli')
if spec:
    d = os.path.dirname(os.path.dirname(spec.origin))
    if os.path.isfile(os.path.join(d, 'hermes_cli', 'gateway.py')):
        print(d); sys.exit(0)
sys.exit(1)
" 2>/dev/null && return
    echo ""
}

HERMES_HOME=$(find_hermes_home "$1")
[ -n "$HERMES_HOME" ] || error "找不到 hermes 安装目录，请手动指定：bash install.sh /opt/hermes"
info "hermes 安装目录：$HERMES_HOME"

PLATFORMS_DIR="$HERMES_HOME/gateway/platforms"
GATEWAY_PY="$HERMES_HOME/hermes_cli/gateway.py"
[ -d "$PLATFORMS_DIR" ] || error "目录不存在：$PLATFORMS_DIR"
[ -f "$GATEWAY_PY" ]   || error "文件不存在：$GATEWAY_PY"

# ── Step 1：安装适配器文件 ────────────────────────────────────
NAPCAT_DIR="$PLATFORMS_DIR/napcat"
info "Step 1/2  安装适配器 → $NAPCAT_DIR"

if [ -d "$NAPCAT_DIR/.git" ]; then
    info "  检测到已有仓库，执行 git pull 更新..."
    git -C "$NAPCAT_DIR" pull --ff-only \
        && success "适配器已更新" \
        || warn "git pull 失败，继续使用当前版本"
elif [ -d "$NAPCAT_DIR" ] && [ "$(ls -A "$NAPCAT_DIR" 2>/dev/null)" ]; then
    warn "$NAPCAT_DIR 已存在且非 git 仓库，跳过克隆"
else
    info "  克隆仓库..."
    if git clone --depth=1 "$REPO_URL" "$NAPCAT_DIR" 2>/dev/null; then
        success "克隆成功"
    else
        warn "直连 GitHub 失败，尝试 gh-proxy 代理..."
        git clone --depth=1 "$PROXY_REPO_URL" "$NAPCAT_DIR" \
            || error "克隆失败，请检查网络"
        success "通过代理克隆成功"
    fi
fi

# ── Step 2：修补 gateway.py ───────────────────────────────────
info "Step 2/2  修补 hermes_cli/gateway.py（添加 NapCat 配置向导）"

if grep -q '"key": "napcat"' "$GATEWAY_PY"; then
    success "gateway.py 已包含 NapCat 条目，跳过"
else
    cp "$GATEWAY_PY" "${GATEWAY_PY}.bak"
    info "  已备份 → ${GATEWAY_PY}.bak"

    # 用 Python 做字符串替换，完全不依赖行号
    python3 - "$GATEWAY_PY" "$NAPCAT_DIR" <<'PYEOF'
import sys, os, re

gateway_py = sys.argv[1]
napcat_dir = sys.argv[2]

content = open(gateway_py, encoding='utf-8').read()

# ── 插入 1：在 _PLATFORMS 列表里，yuanbao 条目之前插入 napcat 条目 ──
napcat_platform_entry = r'''    {
        "key": "napcat",
        "label": "NapCat (QQ)",
        "emoji": "🐧",
        "token_var": "NAPCAT_HTTP_URL",
        "setup_instructions": [
            "1. 安装并运行 NapCat v4.18.1+（https://napneko.github.io）",
            "2. 登录 QQ 账号后，在 NapCat 网络配置中启用 HTTP Server（默认端口 3000）和 WebSocket Server（默认端口 3001）",
            "3. 将两个 Server 的 messagePostFormat 均设为 array",
            "4. 如需 Token 鉴权，在两个 Server 中填写相同的 token 字段",
        ],
        "vars": [
            {"name": "NAPCAT_HTTP_URL", "prompt": "NapCat HTTP API 地址", "password": False,
             "help": "NapCat HTTP Server 地址，例如 http://127.0.0.1:3000"},
            {"name": "NAPCAT_WS_URL", "prompt": "NapCat WebSocket 地址", "password": False,
             "help": "NapCat WebSocket Server 地址，例如 ws://127.0.0.1:3001"},
            {"name": "NAPCAT_TOKEN", "prompt": "访问令牌（可选，留空跳过）", "password": True,
             "help": "与 NapCat Server 配置中 token 字段保持一致，未配置 token 则直接回车跳过"},
            {"name": "NAPCAT_ALLOWED_USERS", "prompt": "允许私聊的 QQ 号（逗号分隔，留空则不限制）", "password": False,
             "is_allowlist": True,
             "help": "白名单：仅允许填写的 QQ 号私聊触发机器人，留空则所有人均可使用"},
            {"name": "NAPCAT_GROUP_ALLOWED_USERS", "prompt": "允许在群聊中触发的 QQ 号（逗号分隔，留空则不限制）", "password": False,
             "help": "群聊白名单：仅允许填写的 QQ 号在群聊中 @ 触发机器人，留空则群内所有人均可触发"},
            {"name": "NAPCAT_ADMIN_USERS", "prompt": "管理员 QQ 号（逗号分隔，留空跳过）", "password": False,
             "help": "拥有 /mute /kick /ban 等管理命令权限的 QQ 号，多个用英文逗号分隔"},
            {"name": "NAPCAT_HOME_CHANNEL", "prompt": "默认投递目标（QQ 号或群号，留空跳过）", "password": False,
             "help": "定时任务结果的默认投递目标：私聊填 QQ 号，群聊填 群号（群聊需加前缀 g:，例如 g:123456789）"},
        ],
    },
'''

# 找 yuanbao 条目开头，在它前面插入
anchor1 = '    {\n        "key": "yuanbao",'
if anchor1 in content:
    content = content.replace(anchor1, napcat_platform_entry + anchor1, 1)
    print("  [1/3] _PLATFORMS 条目插入成功")
else:
    # 兜底：在 _PLATFORMS 列表末尾（"]" 前）插入
    content = re.sub(
        r'(\n\]\s*\n\s*\ndef _platform_status)',
        '\n' + napcat_platform_entry + r'\1',
        content, count=1
    )
    print("  [1/3] _PLATFORMS 条目插入成功（兜底方式）")

# ── 插入 2：_setup_napcat() 函数，插在 _setup_signal 或 _setup_qqbot 之后 ──
setup_napcat_func = '''

def _setup_napcat():
    """全中文交互式向导：NapCat (QQ via OneBot 11)。"""
    platform = next(p for p in _PLATFORMS if p["key"] == "napcat")
    emoji = platform["emoji"]

    print()
    print(color("  ─── 🐧 NapCat (QQ) 配置向导 ───", Colors.CYAN))

    print()
    for line in platform["setup_instructions"]:
        print_info(f"  {line}")

    existing_http = get_env_value("NAPCAT_HTTP_URL")
    if existing_http:
        print()
        print_success("NapCat 已配置。")
        if not prompt_yes_no("  重新配置 NapCat？", False):
            return

    print()
    print_info("  NapCat HTTP Server 地址，例如 http://127.0.0.1:3000")
    http_url = prompt("  NapCat HTTP API 地址", password=False)
    if not http_url:
        print_warning("  已跳过 — 缺少 HTTP 地址，NapCat 将无法正常工作。")
        return
    save_env_value("NAPCAT_HTTP_URL", http_url.strip().rstrip("/"))
    print_success("  已保存 NAPCAT_HTTP_URL")

    print()
    print_info("  NapCat WebSocket Server 地址，例如 ws://127.0.0.1:3001")
    ws_url = prompt("  NapCat WebSocket 地址", password=False)
    if not ws_url:
        print_warning("  已跳过 — 缺少 WebSocket 地址，NapCat 将无法接收消息。")
        return
    save_env_value("NAPCAT_WS_URL", ws_url.strip().rstrip("/"))
    print_success("  已保存 NAPCAT_WS_URL")

    print()
    print_info("  与 NapCat Server 配置中 token 字段保持一致，未配置 token 则直接回车跳过")
    token = prompt("  访问令牌（可选，留空跳过）", password=True)
    if token:
        save_env_value("NAPCAT_TOKEN", token.strip())
        print_success("  已保存 NAPCAT_TOKEN")
    else:
        print_info("  已跳过（未设置访问令牌）")

    print()
    print_info("  白名单：仅允许填写的 QQ 号私聊触发机器人，留空则所有人均可使用")
    allowed = prompt("  允许私聊的 QQ 号（逗号分隔，留空则不限制）", password=False)
    if allowed:
        save_env_value("NAPCAT_ALLOWED_USERS", allowed.replace(" ", ""))
        print_success("  已保存 NAPCAT_ALLOWED_USERS")
    else:
        print()
        access_choices = [
            "开放访问（所有人均可私聊触发机器人）",
            "暂时跳过（稍后在 .env 中手动配置）",
        ]
        access_idx = prompt_choice("  如何处理未授权用户？", access_choices, 0)
        if access_idx == 0:
            save_env_value("NAPCAT_ALLOW_ALL_USERS", "true")
            print_warning("  已开启开放访问 — 所有人均可使用你的机器人！")
        else:
            print_info("  已跳过")

    print()
    print_info("  群聊白名单：仅允许填写的 QQ 号在群聊中 @ 触发机器人，留空则群内所有人均可触发")
    group_allowed = prompt("  允许群聊触发的 QQ 号（逗号分隔，留空则不限制）", password=False)
    if group_allowed:
        save_env_value("NAPCAT_GROUP_ALLOWED_USERS", group_allowed.replace(" ", ""))
        print_success("  已保存 NAPCAT_GROUP_ALLOWED_USERS")
    else:
        print_info("  已跳过（群聊不限制触发用户）")

    print()
    print_info("  拥有 /mute /kick /ban 等管理命令权限的 QQ 号，多个用英文逗号分隔")
    admins = prompt("  管理员 QQ 号（逗号分隔，留空跳过）", password=False)
    if admins:
        save_env_value("NAPCAT_ADMIN_USERS", admins.replace(" ", ""))
        print_success("  已保存 NAPCAT_ADMIN_USERS")
    else:
        print_info("  已跳过")

    print()
    print_info("  定时任务结果的默认投递目标：私聊填 QQ 号，群聊填 g:<群号>（例如 g:123456789）")
    home = prompt("  默认投递目标（留空跳过）", password=False)
    if home:
        save_env_value("NAPCAT_HOME_CHANNEL", home.strip())
        print_success("  已保存 NAPCAT_HOME_CHANNEL")
    else:
        print_info("  已跳过")

    print()
    print_success(f"{emoji} NapCat (QQ) 配置完成！")
    print_info("  确保 NapCat 已启动并登录 QQ 账号后，运行 hermes gateway 开始使用。")

'''

# 找 _setup_signal 或 _setup_qqbot 之后插入
for anchor2_pattern in [
    r'(def _setup_qqbot\(\):.*?\n\n\n)(def _setup_signal)',
    r'(def _setup_signal\(\):)',
]:
    m = re.search(anchor2_pattern, content, re.DOTALL)
    if m:
        insert_before = m.group(0).split('def _setup_signal')[0] if 'signal' in anchor2_pattern else m.group(0)
        break

if 'def _setup_napcat' not in content:
    # 在 def _setup_signal 前插入
    if 'def _setup_signal' in content:
        content = content.replace('def _setup_signal', setup_napcat_func + 'def _setup_signal', 1)
        print("  [2/3] _setup_napcat() 函数插入成功")
    else:
        # 兜底：在文件末尾插入
        content += setup_napcat_func
        print("  [2/3] _setup_napcat() 函数插入成功（末尾兜底）")
else:
    print("  [2/3] _setup_napcat() 已存在，跳过")

# ── 插入 3：路由分支，在 _setup_qqbot() 调用之后插入 ──
if '_setup_napcat()' not in content:
    for route_anchor in [
        '            _setup_qqbot()\n',
        "elif platform[\"key\"] == \"qqbot\":\n            _setup_qqbot()\n",
    ]:
        if route_anchor in content:
            content = content.replace(
                route_anchor,
                route_anchor + '        elif platform["key"] == "napcat":\n            _setup_napcat()\n',
                1
            )
            print("  [3/3] 路由分支插入成功")
            break
    else:
        # 兜底：在 _setup_wecom 路由前插入
        wecom_route = '        elif platform["key"] == "wecom":'
        if wecom_route in content:
            content = content.replace(
                wecom_route,
                '        elif platform["key"] == "napcat":\n            _setup_napcat()\n' + wecom_route,
                1
            )
            print("  [3/3] 路由分支插入成功（兜底方式）")
        else:
            print("  [3/3] 警告：找不到路由插入点，请手动添加")
else:
    print("  [3/3] 路由分支已存在，跳过")

# 写回文件并验证语法
open(gateway_py, 'w', encoding='utf-8').write(content)

import ast
try:
    ast.parse(content)
    print("  语法验证通过")
except SyntaxError as e:
    print(f"  语法错误：{e}，正在恢复备份...")
    import shutil
    shutil.copy(gateway_py + '.bak', gateway_py)
    sys.exit(1)
PYEOF

    if [ $? -eq 0 ]; then
        success "gateway.py 修补完成"
    else
        error "修补失败，已自动恢复备份"
    fi
fi

# ── 完成 ──────────────────────────────────────────────────────
echo ""
success "安装完成！"
echo ""
echo "  运行以下命令完成配置："
echo ""
echo "    hermes gateway setup"
echo ""
echo "  在平台列表中选择 NapCat (QQ) 即可。"

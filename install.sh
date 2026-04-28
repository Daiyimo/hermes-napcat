#!/usr/bin/env bash
# hermes-napcat install script
# 用法：
#   bash install.sh              # 自动检测 hermes 安装目录
#   bash install.sh /opt/hermes  # 手动指定 hermes 安装目录
#
# 功能：
#   1. 将适配器文件克隆/复制到 hermes 的 gateway/platforms/napcat/
#   2. 将 napcat_gateway.patch 应用到 hermes_cli/gateway.py
#      使 `hermes gateway setup` 出现 NapCat (QQ) 配置向导

set -e

REPO_URL="https://github.com/Daiyimo/hermes-napcat.git"
PROXY_RAW="https://gh-proxy.com/https://raw.githubusercontent.com/Daiyimo/hermes-napcat/main"

# ── 颜色输出 ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[hermes-napcat]${NC} $*"; }
success() { echo -e "${GREEN}[hermes-napcat]${NC} $*"; }
warn()    { echo -e "${YELLOW}[hermes-napcat]${NC} $*"; }
error()   { echo -e "${RED}[hermes-napcat]${NC} $*"; exit 1; }

# ── 定位 hermes 安装目录 ──────────────────────────────────────
find_hermes_home() {
    # 1. 命令行参数
    if [ -n "$1" ] && [ -d "$1" ]; then
        echo "$1"; return
    fi
    # 2. 常见安装路径
    for candidate in /opt/hermes /opt/hermes-agent "$HOME/.hermes" "$HOME/hermes-agent"; do
        if [ -f "$candidate/hermes_cli/gateway.py" ]; then
            echo "$candidate"; return
        fi
    done
    # 3. 从 hermes 命令反推
    if command -v hermes &>/dev/null; then
        hermes_bin=$(command -v hermes)
        # 如果是 pip 脚本，找 site-packages
        hermes_dir=$(python3 -c "
import importlib.util, os
spec = importlib.util.find_spec('hermes_cli')
if spec: print(os.path.dirname(os.path.dirname(spec.origin)))
" 2>/dev/null)
        if [ -n "$hermes_dir" ] && [ -f "$hermes_dir/hermes_cli/gateway.py" ]; then
            echo "$hermes_dir"; return
        fi
    fi
    echo ""
}

HERMES_HOME=$(find_hermes_home "$1")
if [ -z "$HERMES_HOME" ]; then
    error "找不到 hermes 安装目录。请手动指定：bash install.sh /path/to/hermes"
fi
info "hermes 安装目录：$HERMES_HOME"

PLATFORMS_DIR="$HERMES_HOME/gateway/platforms"
GATEWAY_PY="$HERMES_HOME/hermes_cli/gateway.py"

[ -d "$PLATFORMS_DIR" ] || error "目录不存在：$PLATFORMS_DIR"
[ -f "$GATEWAY_PY" ]   || error "文件不存在：$GATEWAY_PY"

# ── Step 1：安装适配器文件 ────────────────────────────────────
NAPCAT_DIR="$PLATFORMS_DIR/napcat"
info "Step 1/2  安装适配器文件 → $NAPCAT_DIR"

if [ -d "$NAPCAT_DIR/.git" ]; then
    info "  已有 git 仓库，执行 git pull 更新..."
    git -C "$NAPCAT_DIR" pull --ff-only && success "  适配器已更新" || warn "  git pull 失败，跳过更新"
elif [ -d "$NAPCAT_DIR" ] && [ "$(ls -A "$NAPCAT_DIR")" ]; then
    warn "  $NAPCAT_DIR 已存在且非空（非 git），跳过克隆"
else
    # 尝试直接克隆，失败则走代理
    info "  克隆仓库..."
    if git clone --depth=1 "$REPO_URL" "$NAPCAT_DIR" 2>/dev/null; then
        success "  克隆成功"
    else
        warn "  直连 GitHub 失败，尝试 gh-proxy 代理..."
        PROXY_URL="https://gh-proxy.com/$REPO_URL"
        git clone --depth=1 "$PROXY_URL" "$NAPCAT_DIR" || error "  克隆失败，请检查网络或手动克隆"
        success "  通过代理克隆成功"
    fi
fi

# ── Step 2：打 gateway.py patch ───────────────────────────────
info "Step 2/2  修补 hermes_cli/gateway.py（添加 NapCat 配置向导）"

# 检查是否已经打过补丁
if grep -q '"key": "napcat"' "$GATEWAY_PY"; then
    success "  gateway.py 已包含 NapCat 条目，跳过"
else
    PATCH_FILE="$NAPCAT_DIR/napcat_gateway.patch"
    [ -f "$PATCH_FILE" ] || error "  找不到 $PATCH_FILE"

    # 备份原文件
    cp "$GATEWAY_PY" "${GATEWAY_PY}.bak"
    info "  已备份原文件 → ${GATEWAY_PY}.bak"

    # 应用补丁（先试严格模式，再试模糊匹配）
    if patch -p1 --forward -d "$HERMES_HOME" < "$PATCH_FILE" 2>/dev/null; then
        success "  gateway.py 修补成功"
    elif patch -p1 --forward --fuzz=3 -d "$HERMES_HOME" < "$PATCH_FILE" 2>/dev/null; then
        success "  gateway.py 修补成功（模糊匹配）"
    else
        # patch 失败则恢复备份
        cp "${GATEWAY_PY}.bak" "$GATEWAY_PY"
        error "  自动打补丁失败（hermes-agent 版本可能不兼容）\n  请手动执行：patch -p1 -d $HERMES_HOME < $PATCH_FILE"
    fi
fi

# ── 完成 ──────────────────────────────────────────────────────
echo ""
success "安装完成！"
echo ""
echo "  接下来运行以下命令完成配置："
echo ""
echo "    hermes gateway setup"
echo ""
echo "  在平台列表中选择 NapCat (QQ) 即可。"

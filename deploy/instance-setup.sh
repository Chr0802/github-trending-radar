#!/bin/bash
# 实例侧一次性部署脚本（在 OrcaTerm 里以 root 执行）
#
# 作用：把 GitHub 仓库拉到 /var/www/trending-repo，同步 output/ 到
#       /var/www/trending（Caddy :8080 已指向它），并装 cron 每 10 分钟拉取。
#
# 用法：
#   sudo -i
#   bash instance-setup.sh [仓库URL]
# 默认仓库：https://github.com/Chr0802/github-trending-radar.git
set -e

REPO_URL="${1:-https://github.com/Chr0802/github-trending-radar.git}"
REPO_DIR=/var/www/trending-repo
DEST=/var/www/trending

echo "[1/5] 检查 git ..."
if ! command -v git >/dev/null 2>&1; then
  echo "未安装 git，尝试 apt 安装 ..."
  apt-get update -y && apt-get install -y git
fi

echo "[2/5] 检测 GitHub 连通性 ..."
if ! git ls-remote "$REPO_URL" >/dev/null 2>&1; then
  echo "❌ 无法访问仓库：$REPO_URL"
  echo "   请确认：① 仓库已创建且为 Public；② 实例能访问 github.com（可用 `curl -I https://github.com` 测）"
  exit 1
fi
echo "✅ 仓库可达"

echo "[3/5] 克隆 / 更新仓库 ..."
if [ ! -d "$REPO_DIR/.git" ]; then
  rm -rf "$REPO_DIR"
  git clone "$REPO_URL" "$REPO_DIR"
else
  cd "$REPO_DIR" && git pull --ff-only
fi

echo "[4/5] 同步报告到 $DEST ..."
mkdir -p "$DEST"
cp -a "$REPO_DIR/output/." "$DEST/"

echo "[5/5] 安装 cron（每 10 分钟拉取）..."
cat > /usr/local/bin/trending-pull.sh <<'EOS'
#!/bin/bash
REPO_DIR=/var/www/trending-repo
DEST=/var/www/trending
[ -d "$REPO_DIR/.git" ] || exit 0
cd "$REPO_DIR" && git pull --ff-only >/dev/null 2>&1
mkdir -p "$DEST"
cp -a "$REPO_DIR/output/." "$DEST/"
EOS
chmod +x /usr/local/bin/trending-pull.sh
echo '*/10 * * * * root /usr/local/bin/trending-pull.sh >> /var/log/trending-pull.log 2>&1' > /etc/cron.d/trending-pull
chmod 644 /etc/cron.d/trending-pull

echo ""
echo "✅ 完成。验证：curl -s http://127.0.0.1:8080/ | head -3"
echo "   公网访问：http://43.142.34.105:8080/"
echo "   日志：tail -f /var/log/trending-pull.log"

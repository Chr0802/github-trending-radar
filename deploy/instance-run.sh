#!/bin/bash
# 实例侧：读取 Action 采集的 candidates → 智谱摘要 → 生成 HTML → 直接写入 Caddy 根目录
#
# 由 cron 每 2 分钟调用（见 crontab 配置）。只有 candidates 更新时才真正生成。
# 依赖：python3 + requirements.txt 已安装；/etc/trending-radar/llm.env 提供 LLM Key。
set -e

REPO_DIR=/var/www/trending-repo
DEST=/var/www/trending
STATE=/var/lib/trending-radar/last-candidates
ENV_FILE=/etc/trending-radar/llm.env

cd "$REPO_DIR"
git pull --ff-only >/dev/null 2>&1 || true

NEW_HASH=$(git rev-parse HEAD:data/candidates.json 2>/dev/null || echo none)
LAST_HASH=$(cat "$STATE" 2>/dev/null || echo none)

if [ "$NEW_HASH" = "$LAST_HASH" ] && [ -f "$DEST/index.html" ]; then
  echo "$(date -Is) no new candidates, skip"
  exit 0
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

echo "$(date -Is) generating from candidates $NEW_HASH"
python3 run.py --from-candidates

mkdir -p "$DEST"
cp -a output/. "$DEST/"

mkdir -p "$(dirname "$STATE")"
echo "$NEW_HASH" > "$STATE"
echo "$(date -Is) done"

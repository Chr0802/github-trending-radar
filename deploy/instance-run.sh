#!/bin/bash
# 实例侧：拉候选 → LLM 摘要 → 生成 HTML → 直接写入 Caddy 根目录
#
# 设计要点：
# - candidates 用 curl 拉单个文件（raw.githubusercontent 比整仓 git fetch 轻，且带超时）
# - 代码更新用 git fetch + reset，带超时，失败则用本地代码继续
# - 状态 = candidates md5 + 代码 commit，任一变化都重新生成
set -e

REPO_DIR=/var/www/trending-repo
DEST=/var/www/trending
STATE=/var/lib/trending-radar/last-state
ENV_FILE=/etc/trending-radar/llm.env
PY=/opt/trending-venv/bin/python
CAND_URL=https://raw.githubusercontent.com/Chr0802/github-trending-radar/main/data/candidates.json

cd "$REPO_DIR"

# 1) 代码更新（带超时；实例到 GitHub 慢时不阻塞）
if timeout 45 git fetch origin >/dev/null 2>&1; then
  timeout 20 git reset --hard origin/main >/dev/null 2>&1 || true
  echo "$(date -Is) code updated"
else
  echo "$(date -Is) code fetch failed/timeout, use local"
fi

# 2) candidates：curl 单文件，比整仓 fetch 快且不易卡死
mkdir -p data
if curl -fsSL --max-time 45 "$CAND_URL" -o /tmp/candidates.json 2>/dev/null; then
  mv /tmp/candidates.json data/candidates.json
  echo "$(date -Is) candidates updated"
else
  echo "$(date -Is) candidates fetch failed, use local"
fi

[ -f data/candidates.json ] || { echo "$(date -Is) no candidates, skip"; exit 0; }

CAND_HASH=$(md5sum data/candidates.json | awk '{print $1}')
CODE_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo local)
NEW_STATE="${CAND_HASH}-${CODE_HASH}"
LAST_STATE=$(cat "$STATE" 2>/dev/null || echo none)

if [ "$NEW_STATE" = "$LAST_STATE" ] && [ -f "$DEST/index.html" ]; then
  echo "$(date -Is) no change, skip"
  exit 0
fi

[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

echo "$(date -Is) generating (cand=${CAND_HASH:0:8} code=${CODE_HASH})"
timeout 300 "$PY" run.py --from-candidates

mkdir -p "$DEST"
cp -a output/. "$DEST/"

mkdir -p "$(dirname "$STATE")"
echo "$NEW_STATE" > "$STATE"
echo "$(date -Is) done"

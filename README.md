# github-trending-radar

每日自动采集 GitHub 热门开源项目，生成**深色单文件 HTML 报告**并部署到轻量云，形成「采集 → 摘要 → 部署 → 历史存档」的闭环。

## 特性

- **多维覆盖**：不局限安全方向，按语言（OSS Insight）+ 领域 topic（GitHub Search）采集热门项目。
- **双模式摘要**：配置了 `LLM_API_KEY` 走 DeepSeek 中文摘要 + hype 红蓝旗；未配置则走**代码规则摘要**，零外部依赖也能跑。
- **每期数量可调**：`config.yaml` 的 `top_n`（默认 10）。
- **历史存档**：每期独立 `reports/YYYY-MM-DD.html`，`archive.html` 可回看任意往期。
- **跨期 diff**：标注「🆕 新上榜 / 🔥 连续 N 天」，体现趋势持续性（闭环核心）。
- **日更**：GitHub Action 每日北京时间 09:00 生成并 push 报告，实例 cron 每 10 分钟拉取，Caddy 静态服务。

## 结构

```
config.yaml            可调参数（top_n / 语言 / 领域 topic / LLM）
src/collect.py         采集层：OSS Insight + GitHub Search，合并 enrich
src/summarize_rule.py  规则摘要（降级实现）
src/summarize_llm.py   DeepSeek 摘要
src/summarize.py       统一接口（有 key 走 LLM，否则/失败回退规则）
src/generate.py        深色 HTML 生成（index / 当期 / archive）
run.py                 主流程：采集→摘要→diff→history→HTML
data/history.json      跨期状态持久化（提交到仓库）
output/                生成的报告（index.html / archive.html / reports/）
deploy/instance-setup.sh  实例侧一键部署脚本（clone + cron）
.github/workflows/     每日 Action（只 push 仓库，不做 SSH 部署）
```

## 本地运行

```bash
pip install -r requirements.txt
python run.py                # 可选 GITHUB_TOKEN / LLM_API_KEY 环境变量
```

## 部署架构（实例主动拉取，无需 SSH）

```
GitHub Action: 采集→摘要→生成→git push 公开仓库
                    ↓
实例 cron（每 10 分钟）: git pull → 同步 output/ 到 /var/www/trending
                    ↓
Caddy :8080 → 公网 http://43.142.34.105:8080/
```

选这个架构的原因：TAT 远程命令对 `.ssh`/敏感文件有硬拦截、SSH 又不通，实例主动拉取可完全绕开，且不受本机网络位置影响。

### 首次配置（实例上执行一次）

```bash
sudo -i
curl -fsSL https://raw.githubusercontent.com/Chr0802/github-trending-radar/main/deploy/instance-setup.sh -o /tmp/setup.sh
bash /tmp/setup.sh
```

脚本会：装 git → 检测 GitHub 连通 → clone 到 `/var/www/trending-repo` → 同步 `output/` 到 `/var/www/trending` → 装 cron 每 10 分钟拉取。

若 `curl` raw 失败（GitHub raw 国内常被卡），改用：

```bash
cd /tmp && rm -rf github-trending-radar
git clone https://github.com/Chr0802/github-trending-radar.git
bash /tmp/github-trending-radar/deploy/instance-setup.sh
```

### 仓库设置

- **Actions → General → Workflow permissions** 选 **Read and write**（否则 Action 无法 push）
- 可选：Secrets 加 `LLM_API_KEY`（DeepSeek），摘要质量显著提升

### 访问

- 最新：`http://43.142.34.105:8080/`
- 历史存档：`http://43.142.34.105:8080/archive.html`
- 单期：`http://43.142.34.105:8080/reports/2026-10-28.html`

## 说明

- 采集在 GitHub Action 环境运行（网络正常）；本机直跑若遇 GitHub API TLS 问题需走代理。
- `history.json` 提交到仓库，历史不依赖服务器存活。
- 实例上的 Caddy 用独立 `:8080` 站点，不影响原有 Hermes Agent 的 `:80`。

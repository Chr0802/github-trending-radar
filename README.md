# github-trending-radar

每日自动采集 GitHub 热门开源项目，生成**深色单文件 HTML 报告**并部署到轻量云，形成「采集 → 摘要 → 部署 → 历史存档」的闭环。

## 特性

- **多维覆盖**：不局限安全方向，按语言（OSS Insight）+ 领域 topic（GitHub Search）采集热门项目。
- **双模式摘要**：配置了 `LLM_API_KEY` 走 DeepSeek 中文摘要 + hype 红蓝旗；未配置则走**代码规则摘要**，零外部依赖也能跑。
- **每期数量可调**：`config.yaml` 的 `top_n`（默认 10）。
- **历史存档**：每期独立 `reports/YYYY-MM-DD.html`，`archive.html` 可回看任意往期。
- **跨期 diff**：标注「🆕 新上榜 / 🔥 连续 N 天」，体现趋势持续性（闭环核心）。
- **日更**：GitHub Action 每日北京时间 09:00 运行，SSH 直推轻量云。

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
.github/workflows/     每日 Action + SSH 部署
```

## 本地运行

```bash
pip install -r requirements.txt
python run.py                # 可选 GITHUB_TOKEN / LLM_API_KEY 环境变量
```

## 部署到轻量云（首次一次性配置）

目标实例已用 Caddy 占用 80 端口（Hermes Agent 服务），报告以**子路径**方式挂到 Caddy：

1. 生成部署专用 SSH 密钥对，公钥加进实例 `~/.ssh/authorized_keys`，私钥存 GitHub Secret `SSH_PRIVATE_KEY`。
2. 实例上建目录：`mkdir -p /var/www/trending`
3. 在现有 Caddyfile 内追加（用 `handle_path` 避免抢根路径）：
   ```
   handle_path /trending/* {
       root * /var/www/trending
       file_server
   }
   ```
   然后 `caddy reload`。
4. 仓库 Secrets 配置：`DEPLOY_HOST`（公网 IP）、`DEPLOY_USER`、`SSH_PRIVATE_KEY`、`DEPLOY_DIR`（=/var/www/trending）。可选 `LLM_API_KEY`。

此后每次 Action 运行会自动 scp `output/` 到实例并 reload Caddy，公网 `http://<IP>/trending/` 即可访问。

## 说明

- 采集在 GitHub Action 环境运行（网络正常）；本机直跑若遇 GitHub API TLS 问题需走代理。
- `history.json` 提交到仓库，历史不依赖服务器存活。

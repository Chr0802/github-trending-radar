"""主流程：采集 → 摘要 → 跨期 diff → 写 history → 生成 HTML。

用法：python run.py
环境变量：
  GITHUB_TOKEN         可选，提升 GitHub Search API 限额
  LLM_PROVIDER         可选，deepseek | openrouter；不填则按已注入的 Key 自动探测
  OPENROUTER_API_KEY   可选，配置则走 OpenRouter（可用免费模型），否则规则摘要
  LLM_API_KEY          可选，DeepSeek 等自有 provider 的 Key
"""
from __future__ import annotations

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from collect import load_config, collect
from llm_client import resolve_settings
from summarize import summarize
import generate


def load_history(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(path: str, history: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def apply_diff(repos: list[dict], history: dict, today: str) -> list[dict]:
    """注入 is_new / streak（连续在榜天数）。"""
    dates = sorted(history.keys())
    prev = dates[-1] if dates else None
    prev_names = set(history[prev].get("repos", [])) if prev else set()

    for r in repos:
        name = r["full_name"]
        if name in prev_names:
            r["is_new"] = False
            # 向前追溯连续在榜天数
            streak = 1
            cur = prev
            while True:
                idx = dates.index(cur) - 1
                if idx < 0:
                    break
                cur = dates[idx]
                if name in history[cur].get("repos", []):
                    streak += 1
                else:
                    break
            r["streak"] = streak
        else:
            r["is_new"] = True
            r["streak"] = 1
    return repos


def main() -> None:
    cfg = load_config("config.yaml")
    token = os.environ.get("GITHUB_TOKEN")
    settings = resolve_settings(cfg)

    print("[1/4] 采集热门项目...")
    repos_raw = collect(cfg, token)

    if settings:
        desc = f"{settings['provider']} · {settings['models'][0]}"
        if len(settings["models"]) > 1:
            desc += f" (+{len(settings['models']) - 1} 个候选)"
    else:
        desc = "规则"
    print(f"[2/4] 生成摘要（LLM={desc}）...")
    repos = summarize(repos_raw, cfg, settings)

    today = datetime.date.today().isoformat()
    hist_path = cfg["history_file"]
    history = load_history(hist_path)

    print("[3/4] 跨期 diff + 写历史...")
    repos = apply_diff(repos, history, today)
    history[today] = {
        "date": today,
        "repos": [r["full_name"] for r in repos],
        # 相对站点根目录的路径（部署后 output/ 内容平铺到 /var/www/trending 根）
        "report_path": f"reports/{today}.html",
    }
    save_history(hist_path, history)

    print("[4/4] 生成 HTML...")
    generate.write_all(
        repos, today, history, cfg["output_dir"], cfg["report_dir"]
    )
    print(f"完成：{len(repos)} 个 · {today} · 输出至 {cfg['output_dir']}/")


if __name__ == "__main__":
    main()

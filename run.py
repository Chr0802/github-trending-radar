"""主流程：采集 → 摘要 → 跨期 diff → 写 history → 生成 HTML。

用法：python run.py
环境变量：
  GITHUB_TOKEN  可选，提升 GitHub Search API 限额
  LLM_API_KEY   可选，配置则走 DeepSeek 摘要，否则代码规则摘要
"""
from __future__ import annotations

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from collect import load_config, collect
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
    llm_key = os.environ.get("LLM_API_KEY")

    print("[1/4] 采集热门项目...")
    repos_raw = collect(cfg, token)

    print("[2/4] 生成摘要（LLM=%s）..." % ("DeepSeek" if llm_key else "规则"))
    repos = summarize(repos_raw, cfg, llm_key)

    today = datetime.date.today().isoformat()
    hist_path = cfg["history_file"]
    history = load_history(hist_path)

    print("[3/4] 跨期 diff + 写历史...")
    repos = apply_diff(repos, history, today)
    history[today] = {
        "date": today,
        "repos": [r["full_name"] for r in repos],
        "report_path": f"{cfg['report_dir']}/{today}.html",
    }
    save_history(hist_path, history)

    print("[4/4] 生成 HTML...")
    generate.write_all(
        repos, today, history, cfg["output_dir"], cfg["report_dir"]
    )
    print(f"完成：{len(repos)} 个 · {today} · 输出至 {cfg['output_dir']}/")


if __name__ == "__main__":
    main()

"""采集层：OSS Insight + GitHub Search API 合并去重并 enrich。

设计要点：
- OSS Insight 提供「周期内热门」信号（stars_period / pushes / total_score），比历史总 star 更接近「趋势」。
- GitHub Search API 按 topic 拉取，补领域标签，并直接带 archived / license / pushed_at 等 enrich 字段。
- OSS Insight 失败时自动回退到 Search，保证闭环在零外部依赖下也能跑。
- 本函数假设运行在 GitHub Action 环境（网络正常）；若在本机直跑且抓 GitHub API 遇 TLS 问题，需走代理。
"""
from __future__ import annotations

import os
import time
import requests
import yaml

OSS_API = "https://api.ossinsight.io/v1/trends/repos/"
GH_SEARCH = "https://api.github.com/search/repositories"


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _headers(github_token: str | None) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-trending-radar/1.0",
    }
    if github_token:
        h["Authorization"] = f"Bearer {github_token}"
    return h


def fetch_oss_insight(
    languages: list[str],
    period: str = "past_week",
    per_lang: int = 15,
    timeout: int = 10,
) -> dict[str, dict]:
    """按语言拉 OSS Insight 热门 repo。失败返回空 dict（回退 Search）。"""
    repos: dict[str, dict] = {}
    for lang in languages:
        try:
            url = f"{OSS_API}?period={period}&language={requests.utils.quote(lang)}"
            r = requests.get(url, timeout=timeout)
            if r.status_code != 200:
                print(f"[oss] {lang} 返回 {r.status_code}，跳过")
                continue
            rows = r.json().get("data", {}).get("rows", [])
            for row in rows[:per_lang]:
                name = row.get("repo_name")
                if not name:
                    continue
                repos[name] = {
                    "full_name": name,
                    "language": row.get("primary_language") or lang,
                    "description": (row.get("description") or "").strip(),
                    "html_url": f"https://github.com/{name}",
                    "stars_period": int(row.get("stars") or 0),
                    "forks": int(row.get("forks") or 0),
                    "pushes": int(row.get("pushes") or 0),
                    "score": float(row.get("total_score") or 0),
                    "contributors": row.get("contributor_logins") or "",
                    "collections": row.get("collection_names") or "",
                    "source": "oss_insight",
                }
        except Exception as e:  # noqa: BLE001
            print(f"[oss] {lang} 拉取失败: {e}")
    return repos


def fetch_github_search(
    topics: list[str],
    github_token: str | None = None,
    per_topic: int = 8,
    timeout: int = 20,
) -> dict[str, dict]:
    """按 topic 拉 GitHub Search，补领域标签与 enrich 字段。"""
    repos: dict[str, dict] = {}
    headers = _headers(github_token)
    for topic in topics:
        try:
            q = f"topic:{topic} sort:stars"
            url = (
                f"{GH_SEARCH}?q={requests.utils.quote(q)}"
                f"&sort=stars&order=desc&per_page={per_topic}"
            )
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 403:
                remaining = r.headers.get("X-RateLimit-Remaining", "?")
                reset = r.headers.get("X-RateLimit-Reset", "?")
                has_token = "有" if github_token else "无"
                print(
                    f"[gh] 403 topic={topic} token={has_token} "
                    f"remaining={remaining} reset={reset} body={r.text[:100]}"
                )
                time.sleep(5)
                continue
            if r.status_code != 200:
                print(f"[gh] topic={topic} 返回 {r.status_code}，跳过")
                continue
            items = r.json().get("items", [])
            for it in items:
                name = it.get("full_name")
                if not name:
                    continue
                lic = it.get("license") or {}
                repos[name] = {
                    "full_name": name,
                    "language": it.get("language") or "",
                    "description": (it.get("description") or "").strip(),
                    "html_url": it.get("html_url") or f"https://github.com/{name}",
                    "stars_total": it.get("stargazers_count", 0),
                    "forks": it.get("forks_count", 0),
                    "open_issues": it.get("open_issues_count", 0),
                    "archived": bool(it.get("archived")),
                    "license": lic.get("spdx_id") if lic else None,
                    "pushed_at": it.get("pushed_at") or "",
                    "topics": it.get("topics", []) or [],
                    "owner": (it.get("owner") or {}).get("login")
                    or name.split("/")[0],
                    "source": "github_search",
                    "topic_tag": topic,
                }
            if github_token:
                time.sleep(3)  # GitHub Search secondary rate limit 较严，拉开间隔
        except Exception as e:  # noqa: BLE001
            print(f"[gh] topic {topic} 失败: {e}")
    return repos


def merge_and_rank(oss: dict, gh: dict, top_n: int = 10) -> list[dict]:
    """合并两源：OSS 提供 trend 信号，GH 补 enrich 字段；按 score→stars 排序取 top_n。"""
    merged: dict[str, dict] = {}
    for name, r in oss.items():
        merged[name] = r
    for name, r in gh.items():
        if name in merged:
            merged[name].update(
                {
                    "stars_total": r.get(
                        "stars_total", merged[name].get("stars_total", 0)
                    ),
                    "archived": r.get("archived", merged[name].get("archived", False)),
                    "license": r.get("license", merged[name].get("license")),
                    "pushed_at": r.get("pushed_at", merged[name].get("pushed_at", "")),
                    "topics": r.get("topics", []),
                    "topic_tag": r.get("topic_tag"),
                }
            )
        else:
            merged[name] = r

    items = list(merged.values())
    items.sort(
        key=lambda x: (x.get("score", 0), x.get("stars_total", 0)), reverse=True
    )
    return items[:top_n]


def fetch_readme(
    full_name: str, github_token: str | None = None, max_chars: int = 2000
) -> str:
    """抓 README 前 max_chars 字符（raw 域名不占 GitHub API 限额）。失败返回空串。"""
    headers = _headers(github_token)
    for branch in ("HEAD", "main", "master"):
        url = f"https://raw.githubusercontent.com/{full_name}/{branch}/README.md"
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200 and r.text:
                return r.text[:max_chars]
        except Exception:  # noqa: BLE001
            continue
    return ""


def collect(config: dict, github_token: str | None = None) -> list[dict]:
    oss = fetch_oss_insight(config.get("languages", []))
    gh = fetch_github_search(config.get("topics", []), github_token=github_token)
    top = merge_and_rank(oss, gh, config.get("top_n", 10))
    # 只给最终入选的项目抓 README，控制请求量与耗时
    for r in top:
        r["readme"] = fetch_readme(r["full_name"], github_token)
    return top


if __name__ == "__main__":
    cfg = load_config()
    tok = os.environ.get("GITHUB_TOKEN")
    data = collect(cfg, tok)
    for d in data:
        print(d["full_name"], "score=", d.get("score", 0), "stars=", d.get("stars_total", 0))

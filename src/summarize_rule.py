"""代码规则摘要（无 LLM 时的降级实现）。

输出结构与 summarize_llm 完全一致，保证 generate.py 无感切换：
  domain / star_tier / active / hype_flags / summary
"""
from __future__ import annotations

import datetime as dt

# topic / collection 文本 → 中文领域标签（命中即归类，便于「热门 topic 趋势」聚合）
DOMAIN_MAP = [
    ("ai", "人工智能"),
    ("llm", "大语言模型"),
    ("agent", "AI Agent"),
    ("rag", "RAG"),
    ("security", "安全"),
    ("devops", "DevOps"),
    ("web", "Web 开发"),
    ("rust", "Rust"),
    ("database", "数据库"),
    ("frontend", "前端"),
    ("cli", "命令行工具"),
]

# 营销化描述常见词（仅作轻量红旗信号，不单独判定）
BUZZWORDS = ["revolutionary", "game-changing", "next-gen", "all-in-one", "magic", "ultimate", "best ever"]


def _domain(repo: dict) -> str:
    text = " ".join(
        [
            repo.get("topic_tag", "") or "",
            repo.get("collections", "") or "",
            " ".join(repo.get("topics", []) or []),
            repo.get("description", ""),
        ]
    ).lower()
    for kw, label in DOMAIN_MAP:
        if kw in text:
            return label
    return "综合/其他"


def _star_tier(stars: int) -> str:
    if stars >= 50000:
        return "标杆"
    if stars >= 10000:
        return "知名"
    if stars >= 1000:
        return "成长"
    return "新星"


def _active(pushed_at: str) -> str:
    if not pushed_at:
        return "未知"
    try:
        d = dt.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days = (dt.datetime.now(dt.timezone.utc) - d).days
        return "活跃" if days <= 30 else f"沉睡({days}天未更新)"
    except Exception:  # noqa: BLE001
        return "未知"


def _hype_flags(repo: dict) -> list[str]:
    flags: list[str] = []
    if repo.get("archived"):
        flags.append("已归档·可能停更")
    desc = (repo.get("description") or "").lower()
    if any(b in desc for b in BUZZWORDS) and not (repo.get("stars_total", 0) or 0) > 5000:
        flags.append("描述偏营销化")
    forks = repo.get("forks", 0) or 0
    stars = repo.get("stars_total", 0) or repo.get("stars_period", 0) or 0
    if forks > 0 and stars / max(forks, 1) > 50:
        flags.append("star 远高于 fork·热度高")
    return flags


def derive_metrics(repo: dict) -> dict:
    """星级档位 + 活跃度，供 LLM 摘要与规则摘要共用（纯计算，不依赖 LLM）。"""
    stars = int(repo.get("stars_total", 0) or repo.get("stars_period", 0) or 0)
    return {
        "star_tier": _star_tier(stars),
        "active": _active(repo.get("pushed_at", "")),
    }


def summarize_rule(repos: list[dict], config: dict | None = None) -> list[dict]:
    out = []
    for r in repos:
        stars = int(r.get("stars_total", 0) or r.get("stars_period", 0) or 0)
        domain = _domain(r)
        summary = (
            f"【{domain}】{r.get('description') or '暂无描述'} "
            f"（{r.get('language') or '未知语言'}，{stars:,}★，"
            f"许可证：{r.get('license') or '未声明'}）"
        )
        out.append(
            {
                **r,
                "domain": domain,
                **derive_metrics(r),
                "hype_flags": _hype_flags(r),
                "summary": summary,
            }
        )
    return out

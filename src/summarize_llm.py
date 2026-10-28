"""LLM 摘要（DeepSeek，OpenAI 兼容）。

仅在配置了 LLM_API_KEY 时由 summarize.py 调用；任何异常都交由调用方回退到规则实现。
"""
from __future__ import annotations

import json

from openai import OpenAI

SYSTEM = (
    "你是资深开源项目分析师。对给定的 GitHub 仓库列表，输出 JSON 对象 "
    '{"repos": [...]}，每个元素含：'
    "domain(中文领域标签，如 人工智能/大语言模型/安全/DevOps/Web开发)、"
    "summary(2-3 句中文简介，说清它做什么、解决什么痛点、适合谁)、"
    "hype_flags(风险红旗数组，如 已归档·可能停更/单维护者风险/描述偏营销化)。"
    "严格只输出 JSON，不要多余文字。"
)


def summarize_llm(repos: list[dict], config: dict, api_key: str) -> list[dict]:
    client = OpenAI(
        api_key=api_key, base_url=config.get("llm_base_url")
    )
    model = config.get("llm_model", "deepseek-chat")

    payload = [
        {
            "full_name": r["full_name"],
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "stars": (r.get("stars_total", 0) or r.get("stars_period", 0) or 0),
            "topics": r.get("topics", []),
            "archived": r.get("archived", False),
        }
        for r in repos
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": "请分析以下仓库：\n" + json.dumps(payload, ensure_ascii=False),
            },
        ],
        response_format={"type": "json_object"},
    )
    raw = json.loads(resp.choices[0].message.content)
    arr = raw.get("repos", []) if isinstance(raw, dict) else raw

    by_name = {r["full_name"]: r for r in repos}
    out = []
    for item in arr:
        fn = item.get("full_name")
        base = by_name.get(fn, {})
        out.append(
            {
                **base,
                "domain": item.get("domain", base.get("domain", "综合/其他")),
                "star_tier": base.get("star_tier", ""),
                "active": base.get("active", ""),
                "hype_flags": item.get("hype_flags", []),
                "summary": item.get("summary", base.get("summary", "")),
            }
        )
    return out

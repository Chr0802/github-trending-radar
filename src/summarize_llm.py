"""LLM 摘要（DeepSeek / OpenRouter 免费模型，均走 OpenAI 兼容协议）。

由 summarize.py 在配置了对应 API Key 时调用；任何异常都交由调用方回退到规则实现。
"""
from __future__ import annotations

import json

from llm_client import chat_json, pick_list
from summarize_rule import derive_metrics, summarize_rule

# 注意：必须显式要求模型回填 full_name —— 下游靠它把结果映射回仓库对象。
# 早期版本没写这一句，模型经常自己编仓库名，导致字段全部落空。
SYSTEM = (
    "你是资深开源项目分析师。对给定的 GitHub 仓库列表（含 README 摘录），输出 JSON 对象 "
    '{"repos": [...]}，数组长度和顺序必须与输入一致，每个元素含：'
    "full_name(原样回填输入的仓库全名，不得改写)、"
    "domain(中文领域标签，如 人工智能/大语言模型/安全/DevOps/Web开发)、"
    "summary(4-6 句中文深度介绍，必须结合 README 与 description，依次讲清：① 它是什么、解决什么痛点；"
    "② 核心能力或技术亮点；③ 适合谁、典型使用场景；④ 如何上手（若 README 有安装/命令，用一句话概括）)、"
    "highlights(2-4 条中文短句，每条不超过 22 字，提炼最关键的技术点或差异点；无则空数组)、"
    "pm_insight(2-3 句中文，从产品经理视角分析：① 它背后真实的用户需求是什么；② 产品定位或差异化在哪；"
    "③ 可借鉴的产品方法（功能取舍/体验设计/增长路径）。要具体、结合 README，避免「要注重用户体验」这类空话)、"
    "hype_flags(风险红旗数组，如 已归档·可能停更/单维护者风险/描述偏营销化；无风险给空数组)。"
    "严格只输出 JSON，不要 markdown 围栏，不要多余文字。"
)


def summarize_llm(repos: list[dict], config: dict, settings: dict) -> list[dict]:
    payload = [
        {
            "full_name": r["full_name"],
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "stars": (r.get("stars_total", 0) or r.get("stars_period", 0) or 0),
            "topics": r.get("topics", []),
            "archived": r.get("archived", False),
            "readme": (r.get("readme") or "")[:1800],
        }
        for r in repos
    ]

    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "请分析以下仓库：\n" + json.dumps(payload, ensure_ascii=False),
        },
    ]

    data, model_used = chat_json(
        messages,
        provider=settings["provider"],
        models=settings["models"],
        base_url=settings["base_url"],
        api_key=settings["api_key"],
        headers=settings.get("headers"),
        temperature=float(config.get("llm_temperature", 0.3)),
        # 免费模型多为推理模型，max_tokens 太小会被 reasoning 吃光，正文返回空
        max_tokens=int(config.get("llm_max_tokens", 4096)),
        # 内容为空不算成功，交给调用层换模型重试，而不是整体降级到规则摘要
        validate=lambda d: bool(pick_list(d)),
    )
    print(f"[llm] 摘要完成 · provider={settings['provider']} · model={model_used}")

    arr = pick_list(data)
    if not arr:
        raise ValueError("模型返回的 repos 为空")

    by_name = {r["full_name"]: r for r in repos}
    matched = sum(1 for item in arr if item.get("full_name") in by_name)
    # 免费模型偶尔会改写仓库名或只回一部分，匹配率过低说明数据不可信，交给规则实现兜底
    if matched < max(1, len(repos) // 2):
        raise ValueError(f"full_name 匹配率过低（{matched}/{len(repos)}），疑似模型输出不可信")

    out = []
    for item in arr:
        fn = item.get("full_name")
        base = by_name.get(fn)
        if base is None:
            continue
        out.append(
            {
                **base,
                "domain": item.get("domain", base.get("domain", "综合/其他")),
                # 星级档位与活跃度是纯规则计算，模型给的不可信，统一自己算
                **derive_metrics(base),
                "hype_flags": item.get("hype_flags", []),
                "summary": item.get("summary", base.get("summary", "")),
                "highlights": item.get("highlights", []) or [],
                "pm_insight": item.get("pm_insight", base.get("pm_insight", "")),
            }
        )

    # 模型只覆盖部分仓库时，剩余仓库用规则实现补齐，避免条目丢失
    if len(out) < len(repos):
        done = {r["full_name"] for r in out}
        rest = [r for r in repos if r["full_name"] not in done]
        print(f"[llm] {len(rest)} 个仓库未被模型覆盖，已用规则补齐")
        out.extend(summarize_rule(rest, config))

    return out

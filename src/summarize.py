"""摘要统一接口：有 LLM 配置走 LLM，否则（或失败）回退规则实现。"""
from __future__ import annotations

from summarize_rule import summarize_rule
from summarize_llm import summarize_llm


def summarize(repos: list[dict], config: dict, settings: dict | None = None) -> list[dict]:
    """settings 由 llm_client.resolve_settings() 生成；为 None 表示未配置 LLM。"""
    if settings:
        try:
            return summarize_llm(repos, config, settings)
        except Exception as e:  # noqa: BLE001
            print(f"[llm] 摘要失败，回退规则实现: {e}")
            return summarize_rule(repos, config)
    return summarize_rule(repos, config)

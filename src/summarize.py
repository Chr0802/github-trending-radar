"""摘要统一接口：有 LLM_API_KEY 走 LLM，否则（或失败）回退规则实现。"""
from __future__ import annotations

from summarize_rule import summarize_rule
from summarize_llm import summarize_llm


def summarize(repos: list[dict], config: dict, llm_api_key: str | None = None) -> list[dict]:
    if llm_api_key:
        try:
            return summarize_llm(repos, config, llm_api_key)
        except Exception as e:  # noqa: BLE001
            print(f"[llm] 摘要失败，回退规则实现: {e}")
            return summarize_rule(repos, config)
    return summarize_rule(repos, config)

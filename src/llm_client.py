"""统一 LLM 调用层：DeepSeek / OpenRouter（含免费模型）共用一套入口。

设计目标是「抓一次、稳一次」：日报每天只调用 1 次 LLM，所以宁可多试几个
免费模型，也不要因单个模型 429 就整体降级到规则摘要。

OpenRouter 免费档（`:free` 后缀）的实测坑位，本模块逐个处理：
  1. 429 多为「上游共享池」限流（limit_source=upstream_provider_shared_pool），
     退避重试基本无效，应直接换下一个模型；
  2. 403 可能是 harness 门控（只允许官方 Agent 应用调用）或内容审核拦截；
  3. 404 常是账号隐私设置未允许「免费端点可用于训练」；
  4. 免费模型多为推理模型，max_tokens 太小会被 reasoning 吃光，content 为空；
  5. 输出可能带 ```json 围栏或前后夹带解释文字，需容错提取；
  6. 部分模型不支持 response_format=json_object，会直接 400。
"""
from __future__ import annotations

import json
import os
import random
import re
import time

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

# OpenRouter 免费模型候选（2026-10-28 实测可用，顺序即优先级）。
# 想换模型只需改 config.yaml 的 llm_models，这里只是兜底默认值。
OPENROUTER_FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",  # 550B，100 万上下文，通用最强
    "poolside/laguna-s-2.1:free",              # 实测 2.2s，最稳、指令遵循好
    "cohere/north-mini-code:free",             # 代码向，较慢
    "openrouter/free",                         # 路由器，自动挑可用免费模型
]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"   # 智谱 GLM，OpenAI 兼容

# 智谱 GLM 候选（2026-10-29）：glm-4.7-flash 免费且 200K 上下文，适合日报摘要
ZHIPU_FREE_MODELS = [
    "glm-4.7-flash",   # 免费，200K 上下文，速度快
    "glm-4.6",         # 旗舰，质量更好（按量计费）
]

# 命中即换模型：换模型比重试更有意义
SWITCH_ON = {402, 403, 404, 500, 502, 503, 504}
# 命中则退避重试（同一模型）
RETRY_ON = {429}


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON，兼容 ```json 围栏与前后夹带的解释文字。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("模型返回正文为空")

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"无法从响应中提取 JSON：{text[:200]}")


def pick_list(data, key: str = "repos") -> list:
    """取出结果数组，兼容模型自创 key 名或直接返回顶层数组的情况。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get(key), list):
            return data[key]
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []


def _message_text(msg) -> str:
    """取正文；正文为空时回落到 reasoning 字段（推理模型常见）。"""
    content = (getattr(msg, "content", None) or "").strip()
    if content:
        return content
    extra = getattr(msg, "model_extra", None) or {}
    reasoning = (getattr(msg, "reasoning", None) or extra.get("reasoning") or "").strip()
    if reasoning:
        print(f"[llm] 提示：正文为空，已回落 reasoning 字段（可调大 llm_max_tokens）")
    return reasoning


def _retry_after(err: Exception, attempt: int) -> float:
    """优先用响应头 Retry-After，否则指数退避 + 抖动。"""
    try:
        resp = getattr(err, "response", None)
        if resp is not None:
            val = resp.headers.get("Retry-After")
            if val:
                return min(float(val), 30.0)
    except (TypeError, ValueError, AttributeError):
        pass
    return min(2**attempt + random.random(), 20.0)


def _error_hint(err: Exception) -> str:
    """把 OpenRouter 的 metadata 提炼成一句可读的原因，便于排查。"""
    try:
        body = err.response.json()  # type: ignore[union-attr]
        meta = (body.get("error") or {}).get("metadata") or {}
        bits = []
        if meta.get("limit_source"):
            bits.append(f"limit_source={meta['limit_source']}")
        if meta.get("provider_name"):
            bits.append(f"provider={meta['provider_name']}")
        if meta.get("failed_routing_step"):
            bits.append(f"routing_step={meta['failed_routing_step']}")
        if bits:
            return " / ".join(bits)
    except Exception:  # noqa: BLE001
        pass
    return ""


def _is_json_mode_error(err: Exception) -> bool:
    """判断 400 是否由 response_format 引起（部分模型不支持 json_object）。"""
    text = str(err).lower()
    return "response_format" in text or "json_object" in text or "json mode" in text


def chat_json(
    messages: list[dict],
    *,
    provider: str,
    models: list[str],
    base_url: str,
    api_key: str,
    headers: dict | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    retries: int = 1,
    validate=None,
) -> tuple[dict, str]:
    """按 models 顺序尝试，返回 (解析后的 JSON, 实际生效的模型名)。

    validate: 可选回调，接收解析后的 dict，返回 False 视为本次尝试失败并继续重试。
              用于拦截「JSON 合法但内容不可用」的情况（如 repos 为空数组），
              这种失败应当换模型，而不是直接降级到规则摘要。
    全部失败会抛 RuntimeError，由 summarize() 统一回退到规则实现。
    """
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=40.0,
        max_retries=0,  # 重试策略自己管，避免 SDK 内部重试叠加放大延迟
        default_headers=headers or None,
    )

    errors: list[str] = []
    # 总耗时预算：免费模型可能极慢，超预算直接降级规则摘要，避免 Action 长时间挂起
    budget = float(os.environ.get("LLM_BUDGET_SECONDS", "240"))
    deadline = time.time() + budget
    for model in models:
        if time.time() > deadline:
            errors.append(f"超出 LLM 总预算 {budget:.0f}s，提前结束")
            print(f"[llm] 超出总预算 {budget:.0f}s，停止尝试并降级规则摘要", flush=True)
            break
        print(f"[llm] 尝试模型 {model}（剩余预算 {deadline - time.time():.0f}s）", flush=True)
        for attempt in range(retries + 1):
            # 第一次带 json_object；若模型不支持会 400，之后降级为纯文本 + 容错解析
            use_json_mode = attempt == 0
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **({"response_format": {"type": "json_object"}} if use_json_mode else {}),
                )
            except APIStatusError as e:
                code = e.status_code
                hint = _error_hint(e)
                errors.append(f"{model} → {code} {hint}".strip())

                if code in RETRY_ON:
                    wait = _retry_after(e, attempt)
                    print(f"[llm] {model} 限流({hint or code})，{wait:.1f}s 后重试")
                    time.sleep(wait)
                    continue
                if code == 400 and use_json_mode and _is_json_mode_error(e):
                    print(f"[llm] {model} 不支持 json_object，改为纯文本模式重试")
                    continue
                if code in SWITCH_ON or code == 400:
                    print(f"[llm] {model} 不可用({code} {hint})，切换下一个模型".strip())
                    break
                if code == 401:
                    raise RuntimeError(f"API Key 无效：{e}") from e
                break
            except (APIConnectionError, RateLimitError) as e:
                errors.append(f"{model} → 连接/限流异常 {e}")
                time.sleep(_retry_after(e, attempt))
                continue

            text = _message_text(resp.choices[0].message)
            try:
                data = extract_json(text)
            except (ValueError, json.JSONDecodeError) as e:
                errors.append(f"{model} → JSON 解析失败：{e}")
                print(f"[llm] {model} 输出无法解析为 JSON，重试")
                continue

            if validate is not None and not validate(data):
                errors.append(f"{model} → 内容校验未通过")
                print(f"[llm] {model} 返回内容不合格（如 repos 为空），继续尝试下一个")
                continue

            return data, model

    raise RuntimeError("所有候选模型均失败：" + " | ".join(errors[-5:]))


def resolve_settings(config: dict) -> dict | None:
    """解析运行配置，返回 {provider, models, base_url, api_key, headers}。

    优先级：环境变量 LLM_PROVIDER > config.yaml 的 llm_provider。
    未显式指定时按已注入的 Key 自动探测，方便「只加一个 Secret 就切换」。
    返回 None 表示未配置任何 LLM，直接走规则摘要。
    """
    provider = (os.environ.get("LLM_PROVIDER") or config.get("llm_provider") or "").strip().lower()
    if provider in ("", "auto"):
        provider = ""  # 交给下面的自动探测

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    zhipu_key = os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")
    deepseek_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")

    if not provider:
        # 自动探测顺序：智谱（国内低延迟、中文强）→ OpenRouter（免费）→ DeepSeek
        if zhipu_key:
            provider = "zhipu"
        elif openrouter_key:
            provider = "openrouter"
        elif deepseek_key:
            provider = "deepseek"
        else:
            return None

    if provider == "openrouter":
        api_key = openrouter_key
        if not api_key:
            print("[llm] 选择了 openrouter 但缺少 OPENROUTER_API_KEY，回退规则摘要")
            return None
        models = [m for m in (config.get("llm_models") or []) if m]
        if not models:
            # llm_model 是给 DeepSeek 用的，这里不能拿它兜底，否则会请求到不存在的模型
            models = list(OPENROUTER_FREE_MODELS)
        return {
            "provider": provider,
            "models": list(models),
            # 注意：不能复用 llm_base_url，那是给 DeepSeek 等自有 provider 的
            "base_url": config.get("llm_openrouter_base_url") or OPENROUTER_BASE_URL,
            "api_key": api_key,
            # 可选：在 OpenRouter 排行榜上展示来源，不影响功能
            "headers": {
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "https://github.com"),
                "X-OpenRouter-Title": os.environ.get(
                    "OPENROUTER_SITE_NAME", "github-trending-radar"
                ),
            },
        }

    if provider == "zhipu":
        if not zhipu_key:
            print("[llm] 选择了 zhipu 但缺少 ZHIPU_API_KEY，回退规则摘要")
            return None
        models = [m for m in (config.get("llm_zhipu_models") or []) if m]
        if not models:
            models = list(ZHIPU_FREE_MODELS)
        return {
            "provider": "zhipu",
            "models": list(models),
            "base_url": config.get("llm_zhipu_base_url") or ZHIPU_BASE_URL,
            "api_key": zhipu_key,
            "headers": None,
        }

    # 其余（deepseek 等）走通用 OpenAI 兼容配置
    api_key = deepseek_key
    if not api_key:
        print(f"[llm] 选择了 {provider} 但缺少对应 API Key，回退规则摘要")
        return None
    return {
        "provider": provider,
        "models": [config.get("llm_model") or "deepseek-chat"],
        "base_url": config.get("llm_base_url") or DEEPSEEK_BASE_URL,
        "api_key": api_key,
        "headers": None,
    }

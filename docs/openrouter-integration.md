# OpenRouter 免费模型接入 · 变更说明

> 目标：把日报摘要从「依赖付费 DeepSeek」改为「默认走 OpenRouter 免费模型，失败自动降级」。
> 已验证：端到端真实跑通 1 次（10 个仓库，`nemotron-3-ultra:free`，cost=0），故障注入测试通过。

## 一、改了什么

| 文件 | 变更 | 说明 |
|---|---|---|
| `src/llm_client.py` | **新增** | 统一 LLM 调用层：多模型轮询、429 退避、故障转移、JSON 容错提取、provider 自动探测 |
| `src/summarize_llm.py` | 重写调用部分 | 改用 `llm_client`；补齐 `star_tier`/`active`；`full_name` 匹配率校验；未覆盖仓库用规则补齐 |
| `src/summarize.py` | 签名调整 | 第三参数由 `llm_api_key: str` 改为 `settings: dict`（`resolve_settings()` 的产物） |
| `src/summarize_rule.py` | 抽出 `derive_metrics()` | 星级档位/活跃度计算供 LLM 与规则两条路径共用 |
| `run.py` | 接入 `resolve_settings()` | 启动时打印实际 provider 与候选模型数 |
| `config.yaml` | 新增 LLM 配置段 | `llm_provider: auto`、`llm_models` 候选列表、`llm_temperature`、`llm_max_tokens` |
| `.github/workflows/daily.yml` | 注入新 Secret | 增加 `OPENROUTER_API_KEY` 与 `LLM_PROVIDER` |

改动量：7 个文件，+378 / −43 行。

## 二、怎么启用（2 步）

1. 仓库 **Settings → Secrets and variables → Actions → New repository secret**
   名称 `OPENROUTER_API_KEY`，值填你的 `sk-or-v1-...`
2. 完事。`config.yaml` 里 `llm_provider: auto` 会自动探测到该 Key 并走 OpenRouter。

想强制指定 provider，可在 **Actions → Variables** 加 `LLM_PROVIDER=openrouter`（或 `deepseek`）。

**不想用了**：删掉这个 Secret 即可，自动回落 `LLM_API_KEY`（DeepSeek），再删就纯规则摘要，零依赖。

## 三、为什么这么写（对应实测踩的坑）

| 实测现象 | 代码里的处理 |
|---|---|
| `gemma-4:free` 报 429，`limit_source=upstream_provider_shared_pool` | 区分平台限流与上游池限流；退避后仍失败则换模型（重试无用） |
| `inkling:free` 报 403，`Gate Free Endpoints by Agentic Harness` | 403 不重试，直接切下一个候选模型 |
| `max_tokens=50` 时正文空、`reasoning_tokens=55` | 默认 `max_tokens=2048`；正文空时回落 `reasoning` 字段 |
| 模型输出带 ` ```json ` 围栏或前后夹带解释 | `extract_json()` 剥离围栏 + 截取首个 `{` 到末个 `}` |
| 偶发返回空 `repos` 数组 | 通过 `validate` 回调前移到重试循环，换模型而不是整体降级 |
| 部分模型不支持 `response_format=json_object` | 首次 400 且错误含 `response_format`/`json_object` 时，降级为纯文本模式重试 |
| 模型可能自创 key 名（`projects`/`items`） | `pick_list()` 兜底取第一个对象数组 |

## 四、顺手修的两个原有 bug

1. **`star_tier` / `active` 一直是空值**
   `summarize_llm` 里取的是 `base.get("star_tier")`，但 `base` 是采集层的原始仓库对象，压根没有这两个字段——它们只在 `summarize_rule` 里算。
   现在抽成 `derive_metrics()`，两条路径共用。之前用 DeepSeek 时报告里这两列应该也是空的，可以回看历史报告确认。

2. **`SYSTEM` prompt 没要求模型回填 `full_name`**
   但下游靠 `item.get("full_name")` 做映射。模型一旦改写仓库名，整条记录字段全丢，只剩 `full_name` 为 `None` 被跳过。
   现在 prompt 明确要求「原样回填」，并加了匹配率校验（低于一半直接判为不可信）。

## 五、配额估算

每天 Action 触发 1 次，`summarize` 只调用 1 次 LLM：

- 免费档 **50 次/天**，单次消耗 1 次 → 余量 49 次，重试空间充足
- 充值 10 美元后 1000 次/天，基本不可能打满
- 只有全部候选模型都失败才会降级规则摘要，日报不会断更

## 六、注意事项

1. **提示词会经过第三方免费端点**，厂商可能用于训练。本项目只发公开仓库的 name/description/topics，无敏感信息，可接受；如果以后要抓私有仓库或内部项目，务必切回付费 provider。
2. **模型名单会变**。`config.yaml` 里的 4 个候选是 2026-10-28 的实测结果，几个月后可能失效。届时用 OpenRouter 控制台的 free 筛选页刷新即可，代码无需改。
3. **`llm_base_url` 只对非 openrouter 生效**，OpenRouter 用独立的 `llm_openrouter_base_url`（默认官方地址，需要 EU 路由时才配）。这个坑我第一版就踩了——`llm_base_url` 填的 DeepSeek 地址被 OpenRouter 分支误用，直接 401。
4. 想调摘要风格改 `src/summarize_llm.py` 的 `SYSTEM`；想换模型改 `config.yaml` 的 `llm_models` 顺序即可，不用碰代码。

## 七、应用方式

```bash
# 方式一：打补丁（推荐）
cd github-trending-radar
git apply /path/to/openrouter-integration.patch
git add -A && git commit -m "feat: 接入 OpenRouter 免费模型摘要，支持多模型轮转与自动降级"

# 方式二：直接用本目录文件覆盖同名文件
```

补丁已用 `git apply --check` 验证，可干净应用。

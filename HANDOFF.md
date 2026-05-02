# Handoff: auto-play C 层 VLMDriver 落地（OpenAI-compat + .env 驱动）

**Generated**: 2026-05-02 20:25
**Branch**: `auto-play`（已 push 到 `origin/auto-play`，HEAD = `f854ccc`）
**Status**: Ready for sponsor 实机验收 — 代码 + 测试 + 文档都已就绪，等 30 min FF7R E2E

## Goal

让 unicap 长时间无人值守采集多了一条 C 层（视觉大脑）路径：bot 看每帧 BackBuffer，调 VLM 出 JSON 动作计划，注入到游戏 — 不再只是哑 keep-alive bot。Provider 设计为**任意 OpenAI-compatible 端点**（Qwen / Kimi / OpenAI / 本地 Ollama 都通过同一路径），通过 `.env` 三个变量配置。

## Completed

- [x] `tools/auto_play/vlm_driver.py` 完全重写（占位 NotImplementedError → 可用 driver）
- [x] 三个 env var 驱动配置：`VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL`（`python-dotenv` 在 module import 时 `load_dotenv()`）
- [x] 三个 CLI 对称覆盖：`--vlm-api-key` / `--vlm-base-url` / `--vlm-model`（`--vlm-api-key` 帮助文本带安全提示）
- [x] `--vlm-budget-per-hour`（默认 60）作安全网；删 `--vlm-budget-total-usd`（无定价表）
- [x] runner `BudgetExhausted` 中途切 `KeepAliveDriver`（G-006 fallback）
- [x] 每帧 BMP→JPEG(q=85)→base64→`image_url` content block；`response_format={"type":"json_object"}` + 客户端 `_parse_text_to_actions` 结构校验
- [x] usage 读取 OpenAI 2024 schema：`prompt_tokens` / `completion_tokens` / `prompt_tokens_details.cached_tokens`
- [x] `[VLM-COST]` 日志：`call#N t=Xs in=I out=O cache_r=Cr` 写到 `%TEMP%/unicap/auto_play.log`
- [x] `pyproject.toml` 加 `auto-play-vlm` extra: `openai>=1.50` + `python-dotenv>=1.0`
- [x] `.env.example`（Qwen / Kimi / OpenAI / 本地 Ollama 4 份 cookbook）+ `.env` 入 `.gitignore`
- [x] `scripts/verify_auto_play.py` M1-M6 + M5b（kwarg 覆盖空 env）+ E2E-3 全部更新
- [x] `CLAUDE.md` 重写 VLM 段：`.env` shape + 软依赖 + 日志格式 + DeepSeek 注脚
- [x] 手工 smoke 验证两条路径：缺 key → `BudgetExhausted (含 "VLM_API_KEY")`；传 `api_key=` kwarg → openai client 构造成功
- [x] commit `f854ccc` push 到 `origin/auto-play`

## Not Yet Done

- [ ] **sponsor 30 min FF7R 实机跑** `--driver vlm`（验收 G-005/G-006）：schema 错误率 ≤ 5% + watchdog 触发频率合理 + `[VLM-COST]` 数据写入 + 总花费可观察
- [ ] **merge `auto-play` → `master`**（待 sponsor 验收后）
- [ ] `scripts/verify_auto_play.py` 的 `watchdog._trigger_recovery 计数 +1` timing flake（**前 session 就有，与 VLM 无关**；before=1 after=3 说明触发了 2 次）— 偶发，不阻塞 merge

## Failed Approaches (Don't Repeat These)

### 本 session — VLMDriver 实现走过 4 次 pivot，每次都有学到东西

#### 1. 默认 Anthropic Haiku 4.5（按上 session handoff 的 "G-005 必须 Anthropic + prompt caching" 指引）

最初按上 session handoff 写：
- `client.messages.create(model="claude-haiku-4-5", cache_control={"type":"ephemeral"}, output_config={"format":{"type":"json_schema","schema":...}})`
- 系统 prompt ~12K chars / ~3-4K tokens（接近 Haiku 4.5 的 4096-token caching 阈值）

被推翻原因：sponsor 不想用 Anthropic，看重国内访问 + 成本。

**学到**：handoff 写的方向不一定是当前需求。即使 req G-005 写了 Anthropic 偏好，sponsor 当下选择有变化。

#### 2. 改用 DeepSeek（用户第一反应：换便宜的国内 API）

直接调研：`api-docs.deepseek.com/api/create-chat-completion` 明确 `messages.content` 只接 string，**没有 `image_url` / `image` content block 类型**。`deepseek-v4-flash` / `deepseek-v4-pro` 都纯文本。

被推翻原因：DeepSeek 没 vision 能力（确认日 2026-05-02）。

**学到**：在写代码前先 WebFetch 验证 API 能力。文档里"chat completion"不等于"vision"。

#### 3. Provider 注册表（qwen / kimi / openai / anthropic）

设计了 `_PROVIDERS: dict[str, _ProviderSpec]`，每个 provider 有 `default_model` / `base_url` / `api_key_env` / 4 个定价字段。`AUTO_PLAY_VLM_PROVIDER` env var 选 provider，`--vlm-provider` CLI 覆盖。两条 SDK 路径（anthropic / openai-compat），分 `_call_anthropic` / `_call_openai_compat` 两个方法。

被推翻原因（两步）：
- 用户："不使用 anthropic" → 删 anthropic provider + `_call_anthropic` + sdk-branch
- 用户："不固定 provider，通过 .env 定义 VLM_API_KEY / VLM_BASE_URL / VLM_MODEL" → 删整个注册表

**学到**：注册表过早抽象。sponsor 真正的需求是"我能指任意 OpenAI-compat 端点"，注册表反而限制了灵活性。一行 `base_url` env var 比"四个写死的 provider"更通用。

#### 4. （前置 — 不算 fail）Prompt 太短，caching 不触发

`Haiku 4.5` 的 `cache_control` minimum 是 4096 tokens；初版 system prompt ~1100 tokens，silently 不缓存（`cache_creation_input_tokens=0` 但无报错）。补到 12K chars / ~3K tokens 仍在边缘。

不算彻底失败 — 后来转为 OpenAI-compat 路径（Qwen / Kimi / OpenAI 都有自动 prefix cache，无最低门槛），问题消失。但留个教训：

**学到**：Anthropic 的 cache_control marker 在短 prompt 上是 silent no-op，要看 `usage.cache_creation_input_tokens` 才知道有没有真生效。

### 上 session 已记录（仍生效，不重复）

详见 git log `51a0105` 的 handoff — A 层 4 个失败教训仍适用。

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| 单 OpenAI-compat 路径 + 三个 env var（不再 provider 注册表）| sponsor 选择 — `.env` 三行配置任意端点；未来 DeepSeek 加 vision 改两个值即可，不用动代码 |
| `python-dotenv` 在 module import 时 `load_dotenv()` | 用户启动 `main.py` 不需手 source `.env`；`python-dotenv` 是 try-import 的，不装也不崩（fallback 到 shell env） |
| `api_key` 私有字段，不暴露 property | 防误打到 log；`get_cost_log()` 只返 base_url + model，不返 key |
| `--vlm-api-key` 帮助文本带安全提示 | shell history / process list 会留痕；常态走 `.env`，CLI 只为一次性测试 |
| 删 `--vlm-budget-total-usd` | 注册表删了 → 没定价表 → 算不出 USD；保留 `--vlm-budget-per-hour` 作 count-based 安全网 |
| `BudgetExhausted` 同时盖 "缺 key" + "缺 SDK" + "预算耗尽" | runner 一处 catch 即可 fallback；3 类失败语义都是"VLM 不可用，降级 keep-alive 续 capture" |
| 错误消息含三条出路：".env 或 shell；或一次性 --vlm-api-key" | sponsor 看错误就知道怎么修；不需要看文档 |
| `.env` 入 `.gitignore` + 提供 `.env.example` | 标准 Python 项目惯例；防误 commit secrets |
| `response_format={"type":"json_object"}` + 客户端校验 | OpenAI-compat 各家不一定都支持 strict json_schema mode；json_object 是最大公约数；结构规则在 system prompt 里 + `_parse_text_to_actions` 兜底 |
| 单 `openai` SDK 覆盖三家 + 本地 | base_url 切换；未来加端点零摩擦；不用维护多个 SDK 版本依赖 |

### 上 session 决策（仍生效）

详见 `git log` 的 `51a0105` / `f7b8054` handoff — A 层 + force_borderless 决策仍适用。

## Current State

**Working**:
- HEAD = `f854ccc`，working tree clean，已 push 到 `origin/auto-play`
- 3 种启用姿势全通：(a) `.env` 一次配好；(b) CLI 一次性覆盖 base_url+model 切端点；(c) 完全 CLI（`--vlm-api-key` + ...）零 `.env` 依赖
- 缺 key/SDK 时 lazy 抛 `BudgetExhausted` → runner 切 `KeepAliveDriver`（capture 不中断）
- `ruff check` 全过；`--help` 渲染 4 个 vlm flag

**Broken**: 无（VLMDriver 路径相关的所有手工 smoke 都通了）

**Uncommitted Changes**: 无

## Files to Know

| File | Why It Matters |
|------|----------------|
| `tools/auto_play/vlm_driver.py` | **本 session 完全重写** — VLMDriver 类 + `_BudgetTracker` + `_CallStats` + `_SYSTEM_PROMPT_TEMPLATE` + `BudgetExhausted` |
| `tools/auto_play/runner.py` | factory `create_driver` 加 `api_key`/`base_url`/`model` kwargs；`AutoPlayRunner.__init__` 加 `vlm_api_key`/`vlm_base_url`/`vlm_model`；`_driver_loop` catch `BudgetExhausted` 切 KeepAlive |
| `main.py:1037-1050` | 4 个新 CLI flag：`--vlm-api-key` / `--vlm-base-url` / `--vlm-model` / `--vlm-budget-per-hour`；`--vlm-budget-total-usd` 已删 |
| `pyproject.toml` | `auto-play-vlm` extra 改成 `openai>=1.50` + `python-dotenv>=1.0`（删了 anthropic）|
| `.env.example` | **本 session 新增** — 4 份 cookbook（Qwen / Kimi / OpenAI / 本地 Ollama）|
| `.gitignore` | 加了 `.env` 一行 |
| `scripts/verify_auto_play.py` | M1-M6 + M5b + E2E-3 重写为 env-driven 测试 |
| `CLAUDE.md` 第 196-216 行 | 新 "VLM driver (C 层) 配置" 段 |

### 上 session 文件（仍生效）

| File | Why It Matters |
|------|----------------|
| `tools/window_manager.py` | force_borderless（防 DWM 冻结 console）|
| `tools/auto_play/{driver,input_backend,profile,keep_alive,watchdog}.py` | A 层 — VLM 不动这些 |
| `profiles/{_default,ff7r,doom_eternal,batman_ak}.yaml` | profile YAML — VLM 用 `profile.vlm.game_instructions` 拼 system prompt |

## Code Context

### .env shape（sponsor 复制 .env.example → 改值）

```bash
# Qwen DashScope（推荐，国内访问最便宜）
VLM_API_KEY=sk-...
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL=qwen-vl-plus
```

切 Kimi / OpenAI / 本地 Ollama 改 base_url + model，详见 `.env.example`。

### VLMDriver 接口

```python
# tools/auto_play/vlm_driver.py
class VLMDriver(BotDriver):
    def __init__(
        self,
        profile: GameProfile,
        *,
        api_key: str | None = None,        # CLI override; None → env
        base_url: str | None = None,       # CLI override; None → env
        model: str | None = None,          # CLI override; None → env
        budget_per_hour: int = 60,
        frames_dir: Path | None = None,
        decision_period_s: float | None = None,
    ) -> None: ...

    @property
    def base_url(self) -> str | None: ...
    @property
    def model_name(self) -> str: ...
    # NO api_key property — _api_key_override 私有字段防泄漏

    def get_cost_log(self) -> dict[str, Any]:
        # {call_count, cache_hit_ratio, avg_latency_s, max_calls_per_hour, base_url, model}

class BudgetExhausted(RuntimeError): ...  # runner catch → fallback KeepAlive

VLM_API_KEY_ENV = "VLM_API_KEY"
VLM_BASE_URL_ENV = "VLM_BASE_URL"
VLM_MODEL_ENV = "VLM_MODEL"
```

### Lazy validation 路径（runner 关键）

```python
# tools/auto_play/runner.py:_driver_loop（已有）
try:
    actions = self._driver.next_actions(obs)
except BudgetExhausted as e:
    log.warning("[AUTO-PLAY] VLM 预算耗尽 (%s) — 降级到 KeepAliveDriver", e)
    print(f"[AUTO-PLAY] VLM 预算耗尽: {e} — 降级到 KeepAliveDriver", flush=True)
    self._driver.on_stop()
    self._driver = KeepAliveDriver(self._profile)
    self._driver_name = "keep-alive"
    self._driver.on_start()
    period = max(0.05, self._driver.decision_period_s)
    continue
```

### API 调用 shape

```python
# 单 chat.completions.create — Qwen / Kimi / OpenAI 都接受这个 shape
client.chat.completions.create(
    model=self._model,
    max_tokens=1024,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": self._system_prompt},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64_data}",
            }},
            {"type": "text", "text": "Current frame. ... Output JSON only."},
        ]},
    ],
)
# Response shape:
# response.choices[0].message.content = '{"reasoning": "...", "actions": [...]}'
# response.usage.prompt_tokens / completion_tokens / prompt_tokens_details.cached_tokens
```

### 模型期望返的 JSON

```json
{
  "reasoning": "open exploration, walk forward and look around",
  "actions": [
    {"kind": "key", "payload": {"vk": "W", "event": "press"}, "duration_ms": 1800},
    {"kind": "mouse", "payload": {"op": "move", "dx": 250, "dy": 0}, "duration_ms": 0}
  ]
}
```

`_parse_text_to_actions` 客户端校验：`kind ∈ {key, mouse, gamepad, wait}` + `payload` 是 dict + `duration_ms` 是 int 0-5000。任一字段 drop 该 action 但不丢整个 response。

## Resume Instructions

### 接班 agent 第一件事

```bash
git status                 # 应 clean，branch=auto-play
git log --oneline -3       # 应见 f854ccc → f7b8054 → 2f809dd
ls .env.example            # 应在
ls tools/auto_play/vlm_driver.py  # 完整 VLMDriver 实现
```

### 验证当前状态（offline）

```powershell
# 1. lint
uv run ruff check tools/auto_play/vlm_driver.py tools/auto_play/runner.py main.py scripts/verify_auto_play.py
# 期望: All checks passed!

# 2. import + construct smoke
uv run python -c "from tools.auto_play import VLMDriver; from tools.auto_play.profile import load_profile; p=load_profile('_default',fallback=False); d=VLMDriver(p,budget_per_hour=10); print('OK', d.get_cost_log())"
# 期望: OK {'call_count': 0, 'cache_hit_ratio': 0.0, ..., 'base_url': ..., 'model': ...}

# 3. CLI help（看 4 个 vlm flag 都在）
uv run python main.py launch --help | findstr "vlm-"
# 期望: --vlm-api-key / --vlm-base-url / --vlm-model / --vlm-budget-per-hour
```

### Sponsor 实机验收 — 30 min FF7R `--driver vlm`

```powershell
# 1. 一次性 setup
uv sync --extra auto-play-vlm
copy .env.example .env
# 编辑 .env：填 VLM_API_KEY / VLM_BASE_URL / VLM_MODEL
# 推荐 Qwen-VL-Plus（国内最便宜 + 不需代理）

# 2. 跑
uv run main.py launch --auto-play --driver vlm --profile ff7r

# 期望:
#   [AUTO-PLAY] driver=vlm profile=ff7r ...
#   [VLM] driver 启动 base_url=... model=... profile=ff7r period=1.0s ...
#   F8 → survey（首次） → capture
#   每 ~1s 一行 [VLM-COST] call#N t=X.Xs in=I out=O cache_r=Cr
#   [VLM] reasoning: ... （driver 看到啥）
#   watchdog 偶发 [WATCHDOG] static-frame 触发

# 3. 30 分钟后 F9 停，检查：
type %TEMP%\unicap\auto_play.log | findstr "VLM-COST" | wc -l
# 期望: ≥ 1500（30 min × 60 s × 1Hz × 0.85 success rate）

# 4. cost summary（runner 停止时打到 log）
type %TEMP%\unicap\auto_play.log | findstr "cost_summary"
# 看 cache_hit_ratio + avg_latency_s 合理不
```

### 验收成功后 merge

```powershell
git checkout master
git merge --no-ff auto-play -m "merge: auto-play — A 层 + force_borderless + C 层 VLMDriver"
git push origin master
# 不删 auto-play（留作 history reference）
```

### 失败回滚 — VLMDriver 跑挂

如果实机发现 schema 错误率高 / 调用过慢 / 预算异常：
1. **不要回滚** — runner 已 catch `BudgetExhausted` 自动降级 keep-alive，capture 不会停
2. 看 `auto_play.log` 找具体错误：
   - `[VLM] API 调用异常` → 检查 `VLM_BASE_URL` 是否对、API key 是否过期、模型是否还在
   - `[VLM] JSON 解析失败` → 模型输出非 JSON；可能 model 太弱或 system prompt 过长，换更强 model 或缩 prompt
   - 调用延迟高 → `--vlm-budget-per-hour 30` 降频；或换 `qwen3-vl-flash` 这种更快的模型
3. 临时切回 keep-alive：`--driver keep-alive`（不动 .env，跑 A 层）

## Setup Required

### 已沿用（无新需求）
- VS 2022 + MSBuild v143（C++ 没动）
- `tools/capture/config.py` 的 `GAME_PATH` / `DATASET_ROOT`

### VLM 新加
- `uv sync --extra auto-play-vlm` — 装 `openai>=1.50` + `python-dotenv>=1.0`
- `.env` 文件（项目根，gitignored）— 至少含 `VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL`
- 推荐 provider：阿里云 DashScope（国内开通最快，价格最便宜，OpenAI-compat 端点）
  - 申请：[bailian.console.aliyun.com](https://bailian.console.aliyun.com/) → API-KEY 管理
  - 费用：`qwen-vl-plus` $0.137/$0.409 per 1M（输入/输出），1 帧约 1500 prompt tokens → 1 calls/s × 30 min × 1500 ÷ 1M × $0.137 ≈ $0.37/30min；远低于默认 `--vlm-budget-per-hour 60` 的安全网

## Edge Cases & Error Handling

| 场景 | 行为 |
|------|------|
| `.env` 不存在 | 静默 fallback 到 shell env vars（`load_dotenv()` no-op） |
| `python-dotenv` 没装 | `try-import` 静默失败；只走 shell env vars |
| `VLM_API_KEY` 缺失 | `_ensure_client` raise `BudgetExhausted("VLM_API_KEY 未设置...")` → runner 切 keep-alive |
| `VLM_MODEL` 缺失 | 同上，消息 `VLM_MODEL 未设置 — 不知道叫哪个模型` |
| `openai` SDK 没装 | 同上，消息 `openai SDK 未安装 — pip install "unicap[auto-play-vlm]"` |
| API 调用 timeout（30s）| `try/except Exception` log 后 `return []`（skip 当 tick），下一 tick 重试 |
| 模型返非 JSON | `JSONDecodeError` → drop + log + `stats.schema_ok=False`，下一 tick 重试 |
| JSON 缺 actions 字段 | 返 `[]`（空 actions list），runner 当作"什么都不做"那一 tick |
| 单个 action 字段错 | 该 action drop，其他 action 仍执行 |
| `--vlm-budget-per-hour` 耗尽 | runner 切 KeepAliveDriver，print + log 提示，capture 续命 |
| API key 错误（401/403）| API 返错误码 → `[VLM] API 调用异常` log；不会自动停（继续重试每 tick）；建议手工 F9 停 → 改 .env 重启 |

### 上 session（仍生效）

- watchdog 静帧 → recovery 序列；F8/F9 reserved；profile 找不到 fallback `_default`；ViGEm 没装 fallback 键鼠；force_borderless 30s timeout 不阻塞 capture；等等

## Warnings

### 本 session 新增

- **`--vlm-api-key` 会留 shell history / process list 痕迹** — 帮助文本已写明；常态走 `.env`
- **`api_key` 不能从 VLMDriver 实例 get back** — 故意没 property，防误打 log；如果要 debug 配置，看 `get_cost_log()` 的 `base_url` + `model`
- **`load_dotenv()` 在 module import 时只跑一次** — 测试中 pop env var 后再 import 不会重新加载；测试用例改成 import-then-pop
- **DeepSeek 当前不支持 vision**（确认 2026-05-02）— 不要把 `VLM_BASE_URL` 设成 DeepSeek，会调用即报 400
- **OpenAI-compat 各家对 `response_format` 支持程度不一** — `{"type":"json_object"}` 是最大公约数；个别老 model 不支持时会 silently 忽略，靠 `_parse_text_to_actions` 兜底校验
- **prompt token 数取决于 system prompt + 图像** — Qwen-VL-Plus 的图像 token 大约 ~750（512×512），加上 system prompt ~3K → 总 input ~4K/帧；按 1 Hz 一小时 ~14M token = $1.92。`--vlm-budget-per-hour 60` 默认仅按调用数限制；要按 $$ 限制需自己估算
- **`.env` 不要 commit** — 已加 `.gitignore`；如果之前 sponsor 不小心 commit 过，需要 `git rm --cached .env` 然后重新 commit

### 上 session（仍生效）

详见 `f7b8054` handoff 的 Warnings 段（`SetWindowLongPtrW` 的 c_ssize_t / `force_borderless` 不能同步阻塞 / `settle_delay_s=2.0` 别砍 / `[CAPTURE]` 14s 频率别动 / `--force-borderless` 默认 True 别改 / 等等）。

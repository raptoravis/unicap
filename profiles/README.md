# profiles/ — 自动玩游戏 (auto-play) 配置

每个 `<game>.yaml` 描述一款游戏的控制、keep-alive 行为序列、watchdog 参数、VLM 操作约定。`tools/auto_play/profile.py` 会按 `--profile` 参数加载（fuzzy match 命中 exe 名），找不到时回落 `_default.yaml`。

## 接入新游戏 — 5 步

1. **复制 fallback**：`cp profiles/_default.yaml profiles/<your_game>.yaml`
2. **改 `controls`**：根据游戏内绑定改 `move_forward`、`attack` 等字段
   - 键盘：直接写 vk 名，如 `W`、`SPACE`、`ESC`
   - 鼠标按键：`mouse_left` / `mouse_right` / `mouse_middle`
   - 手柄按钮：`gamepad_X` / `gamepad_A` / 等（仅当 ViGEm 装好 + `input.prefer_gamepad: true`）
3. **改 `keep_alive.sequence`**：按你期望的 bot 行为节奏调整
   - RTS 类无前进键？换成 `press_key` + `mouse_click`
   - 节奏快游戏减小 `period_s`
4. **改 `vlm.game_instructions`**：写一段（中/英文均可）告诉 VLM 这游戏怎么玩。仅在 C 层启用后生效，但建议本 release 一并写好。
5. **测一遍**：`uv run main.py launch --game-path <exe> --auto-play --profile <your_game>` 跑 30 分钟，看 `auto_play.log` 调参数；满意后 commit 进仓库。

## Profile schema 字段说明

```yaml
name:        # 必填，与文件名 stem 一致
description: # 必填，自由文本

controls:    # 必填 dict
  move_forward / move_back / move_left / move_right:
    # vk 名（键盘）或 mouse_<btn> 或 gamepad_<btn>
  turn_axis:
    # 'mouse' | 'gamepad_rstick'
  attack / interact / jump:
    # 同上

reserved_keys:   # 必填 list[str]
  # 必须包含 F8, F9（unicap 自身热键，bot 永不注入）

input:
  prefer_gamepad: bool
  mouse_sensitivity: float

keep_alive:
  period_s: float          # driver 决策周期（秒）
  sequence:                # bot 主行为循环
    - {action: <name>, duration_ms: int, payload?: dict}
  recovery:                # watchdog 触发后的恢复输入序列
    - 同上

watchdog:
  sample_period_s: float
  static_diff_threshold: float       # 0-1，归一化平均像素 diff
  consecutive_static_required: int   # 连续触发次数

vlm:
  game_instructions: str             # 给 VLM 的操作约定段
  frame_subsample_long_edge: int     # 喂 VLM 的图缩到长边 ≤ N px
```

## `keep_alive.sequence` / `recovery` 中可用的 action

| action          | payload                                         | 行为 |
|-----------------|-------------------------------------------------|------|
| `move_forward` / `move_back` / `move_left` / `move_right` | (none) | 按住 controls.move_<dir> 持续 duration_ms |
| `turn`          | `{direction: left\|right\|random, magnitude: float}` | 鼠标 dx 扰动或右摇杆 X |
| `attack` / `interact` / `jump` | (none) | 按 controls.<name> 一次 |
| `press_key`     | `{vk: <name>}`                                  | 按指定键一次（用于 ESC、ENTER 等） |
| `stick_jitter`  | (none)                                          | 左摇杆随机扰动（仅 prefer_gamepad） |
| `wait`          | (none)                                          | 空转 duration_ms |

## 内置 profile

| 文件 | 适用 | 备注 |
|------|------|------|
| `_default.yaml` | 通用 fallback | WASD + 鼠标 + 空格 + E |
| `ff7r.yaml` | FF7 Remake / Intergrade | UE4 / DX12 |
| `doom_eternal.yaml` | DOOM Eternal | id Tech 7 / Vulkan；HUD 是 3D 几何 |
| `batman_ak.yaml` | Batman Arkham Knight | UE3 fork / DX11 |

## 已知坑

- **反作弊**：unicap 不绕反作弊。如果游戏检测到 SendInput 合成输入直接踢人/封号，那是 profile 作者的取舍。
- **Steam 重启游戏**：env vars 失效但 SendInput 仍工作（OS 级注入），auto-play 不受影响。
- **F8/F9 reserved**：profile schema 强制 `reserved_keys` 含 F8、F9 — 改不掉这俩。
- **FF7R cutscene / DOOM Eternal 关卡过场**：watchdog 静帧检测会触发 ESC 尝试跳过；FF7R 有些 cinematic 不能 ESC，靠 ENTER。两者都加进了 recovery 序列。

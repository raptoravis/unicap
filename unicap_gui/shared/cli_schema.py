"""CLI flag schema —— 声明式描述 main.py 的 launch / video / pack 三个 subcommand。

数据驱动：FlagForm widget 读 schema 生成控件，CLIPreview 读 schema + 表单值拼命令行。
新加 / 改 main.py 的 flag 时，只改这里一处。

字段全部对齐 main.py:1101+ 的 argparse 定义；测试 MH-2/MH-3 是清点对照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 类型 ──────────────────────────────────────────────────────────────────────


@dataclass
class FlagSpec:
    """一个 CLI flag 的声明式描述。"""

    name: str  # `--game-path`
    kind: str  # "str" | "path" | "int" | "float" | "choice" | "bool" | "bool_optional" | "store_true"
    default: Any = None
    choices: list[str] | None = None
    help: str = ""
    metavar: str = ""
    # path kind 限定：file（必须存在的文件）/ dir（目录）/ optional_path（可空）
    path_kind: str | None = None  # "file" | "dir" | "optional_dir" | "optional_path" | None
    # int/float SpinBox 的 specialValueText：当值 == minimum 时控件显示这段文字
    # 而非数值。配合 default 设成 minimum 让"默认值"显示成易读 token（如 "auto"）。
    special_value_text: str = ""
    # float SpinBox 显示的小数位数；默认 2，遇到学习率（3e-4 等）这类小数需调大。
    decimals: int = 2
    # 分组名 —— FlagForm 按这个把表单分块显示，同组的 flags 放在一起。
    # 空 / "通用" 都归到默认组。
    group: str = "通用"
    # 详细 tooltip（hover 悬停显示）；空时回落 help。支持多行。
    tooltip: str = ""

    def cli_key(self) -> str:
        """argparse 把 `--game-path` 转 `args.game_path`，反向用。"""
        return self.name.lstrip("-").replace("-", "_")


@dataclass
class SubcommandSchema:
    name: str  # "launch"
    help: str
    flags: list[FlagSpec] = field(default_factory=list)


# ── launch ────────────────────────────────────────────────────────────────────


LAUNCH = SubcommandSchema(
    name="launch",
    help="部署 + 启动游戏 + 进入交互式 F8/F9 工作流",
    flags=[
        # ── 基础 ─────────────────────────────────────────────
        FlagSpec("--game-path", "path", group="基础",
                 default=r"E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe",
                 path_kind="file",
                 help="游戏 exe 完整路径",
                 tooltip="目标游戏的可执行文件完整路径。\n"
                         "支持 DX12/DX11（默认）和 Vulkan（--api vulkan）。\n"
                         "Vulkan-only 游戏（如 DOOM Eternal）必须显式 --api vulkan。"),
        FlagSpec("--dataset-root", "path", default=r"D:\unicap_output",
                 path_kind="optional_dir", group="基础",
                 help="dataset 输出根目录",
                 tooltip="所有采集会话的根目录。\n"
                         "完整路径 = <dataset-root>/<game_exe_name>/<YYYYMMDD_HHMMSS>/\n"
                         "默认与 tools/capture/config.py:DATASET_ROOT 同步。"),
        FlagSpec("--ui-mode", "choice", default=None,
                 choices=["", "no-ui", "ui", "both"], group="基础",
                 help="no-ui=只 pre-UI；ui=只 post-UI BB；both=双流；空=自动",
                 tooltip="决定哪种 BMP 流被采集：\n"
                         "• no-ui — pre-UI scene RT（适合 BC 训练，干净场景）\n"
                         "• ui    — post-UI BackBuffer（含 HUD；id Tech 7 / DOOM 必须用这个）\n"
                         "• both  — 同时落两份\n"
                         "• 空    — 跟随 --auto-play 自动选 no-ui"),
        FlagSpec("--api", "choice", default="auto",
                 choices=["auto", "dx", "vulkan"], group="基础",
                 help="渲染后端",
                 tooltip="auto = 按 exe 名启发（含 vk/vulkan 字串 → vulkan，否则 dx）\n"
                         "dx     = DXGI proxy（dxgi.dll 替换）\n"
                         "vulkan = Vulkan implicit layer（env vars 注入，不修改游戏目录）"),
        FlagSpec("--vk-debug", "store_true", default=False, group="基础",
                 help="Vulkan loader debug 日志",
                 tooltip="VK_LOADER_DEBUG=layer，输出到 %TEMP%/unicap/vk_loader.log。\n"
                         "调 Vulkan 注入失败时打开。"),

        # ── 窗口 / 提示 ──────────────────────────────────────
        FlagSpec("--hints", "bool_optional", default=True, group="窗口/提示",
                 help="显示操作提示",
                 tooltip="控制 console 启动日志 + addon overlay 是否显示 F8/F9 等热键提示。\n"
                         "录视频展示时建议关掉避免遮挡。"),
        FlagSpec("--force-borderless", "bool_optional", default=True, group="窗口/提示",
                 help="强制 borderless 撑满显示器",
                 tooltip="启动后用 SetWindowLongPtrW 把游戏窗口 style 改成 WS_POPUP，\n"
                         "撑满显示器。视觉同全屏，但 DWM 不再暂停 console 渲染\n"
                         "（按 F8/F9 后 [CAPTURE] 等 print 实时显示）。"),

        # ── Auto-Play ────────────────────────────────────────
        FlagSpec("--auto-play", "store_true", default=False, group="Auto-Play",
                 help="启用 bot 自动玩",
                 tooltip="启动 AutoPlayRunner —— bot 在 capture 期间持续注入键鼠/手柄输入。\n"
                         "F9 停止 capture 时一并停。\n"
                         "无人值守长跑必备。"),
        FlagSpec("--driver", "choice", default="auto",
                 choices=["auto", "keep_alive", "bc", "hybrid"], group="Auto-Play",
                 help="auto-play driver 类型",
                 tooltip="auto       — 用 profile.driver 字段（默认 keep_alive）\n"
                         "keep_alive — 纯脚本：按 profile 的 sequence 循环（不用模型）\n"
                         "bc         — 纯 ONNX 模型：每 33ms 推理一次注入按键\n"
                         "hybrid     — BC + 每 N 秒穿插一步 keep_alive（推荐冷启动，防卡死）\n\n"
                         "bc / hybrid 需要 profile.yaml 里有 bc: 块 + model.onnx 已训练。"),

        # ── 数据标注 ─────────────────────────────────────────
        FlagSpec("--record-demo", "store_true", default=False, group="数据标注",
                 help="录人类 demo 模式（F6/F7 标段）",
                 tooltip="人类玩 + 标段：F6=后续帧标 good (quality=1)，F7=后续帧标 bad (quality=2)。\n"
                         "训练时 good 权重 1.0 / bad 丢弃 / 未标 0.5。\n"
                         "与 --auto-play 互斥（自动禁 bot）。\n"
                         "首次采集这个游戏的训练数据用这个模式。"),
        FlagSpec("--record-recovery", "store_true", default=False, group="数据标注",
                 help="DAgger：人工接管期间样本标 good_recovery",
                 tooltip="搭配 --auto-play 使用（不勾 auto-play 无效）。\n"
                         "bot 在玩，你按键期间帧标 quality=3（good_recovery）；\n"
                         "训练 train-bc 时这些帧权重 ×2（默认）—— 模型学会从卡死状态走出来。\n"
                         "DAgger 标准做法。"),

        # ── 输出 ─────────────────────────────────────────────
        FlagSpec("--capture-duration", "float", default=60.0,
                 metavar="SECONDS", group="输出",
                 help="单次 capture 时长（秒，0=不限时）",
                 tooltip="单次 capture 持续时间。\n"
                         "到时自动 roll 新 session（等同自动 F9→F8）。\n"
                         "F9 终止整轮。0 = 不限时（旧行为）。\n"
                         "长跑无人值守建议 300-600，便于 ML batch 化。"),
        FlagSpec("--video", "bool_optional", default=False, group="输出",
                 help="F9 停止后立即生成 video.mp4",
                 tooltip="开了之后 F9 停止 capture 后直接编码 MP4。\n"
                         "关掉只落帧（事后用 video 子命令批量补）。"),
        FlagSpec("--mask-ui", "store_true", default=False, group="输出",
                 help="额外生成 video_masked.mp4",
                 tooltip="basis: depth==0 或 >=0.999 像素（reverse-Z 下的 UI/天空）置黑。\n"
                         "并存而非替换 video.mp4。\n"
                         "DOOM Eternal 等 HUD 是 3D 几何 → mask 抓不到 HUD，仅去 sky。"),
        FlagSpec("--pack", "store_true", default=False, group="输出",
                 help="F9 停止后立即打包 HDF5",
                 tooltip="开了之后 F9 停止 capture 后直接打包成 dataset.h5。\n"
                         "关掉只落帧（事后用 pack 子命令批量补）。"),
        FlagSpec("--color", "choice", default="no-ui",
                 choices=["no-ui", "ui"], group="输出",
                 help="--pack 时哪种图进 /color",
                 tooltip="no-ui = BackBuffer.png（pre-UI 干净）\n"
                         "ui    = BackBufferUI.png 优先（含 HUD；不存在 fallback）"),
        FlagSpec("--normal", "store_true", default=False, group="输出",
                 help="--pack 时同时打包 /normal",
                 tooltip="包 /normal 数据集（normal 贴图）。\n"
                         "占空间大且常常用不到，默认关。"),
        FlagSpec("--no-depth", "store_true", default=False, group="输出",
                 help="跳过 depth EXR 落盘（FC_ExportDepth=0）",
                 tooltip="addon 不输出 DepthBuffer.exr。\n"
                         "BC 训练只用 color → 省掉单线程 EXR ZIP 编码，\n"
                         "1080p 采集实测瓶颈之一。"),
    ],
)


# ── train-bc ──────────────────────────────────────────────────────────────────


TRAIN_BC = SubcommandSchema(
    name="train-bc",
    help="离线训 behavior-cloning 模型（需 uv sync --extra train）",
    flags=[
        # ── 数据源 ───────────────────────────────────────────
        FlagSpec("--profile", "str", default="", group="数据源",
                 help="profile 名（决定 controls + 输出目录；必填）",
                 tooltip="profiles/<name>.yaml 决定：\n"
                         "• controls（哪些按键参与训练）\n"
                         "• 输出目录默认值 (models/<profile>/)\n"
                         "Profile 不存在时会从 _default.yaml 生成模板，需先编辑 controls。"),
        FlagSpec("--raw", "store_true", default=False, group="数据源",
                 help="直读 frames/ + inputs.jsonl（跳过 pack）",
                 tooltip="勾选：--dataset 应指向 session 目录（含 frames/ + inputs.jsonl）\n"
                         "不勾：--dataset 是 dataset.h5 路径或 glob\n\n"
                         "raw 模式首次 epoch 慢（解码 BMP），之后会用 .bc_cache_HxW/ 缓存提速。"),
        FlagSpec("--dataset", "path", default="", metavar="PATH/GLOB",
                 path_kind="optional_path", group="数据源",
                 help="HDF5 路径/glob 或 session 目录（--raw 时）",
                 tooltip="非 raw：dataset.h5 路径或 glob（如 D:/data/*/dataset.h5）\n"
                         "raw 模式：session 目录（含 frames/ + inputs.jsonl）\n"
                         "不传则扫 DATASET_ROOT/<profile>/*/"),
        FlagSpec("--output", "path", default="", metavar="DIR",
                 path_kind="optional_dir", group="数据源",
                 help="输出目录",
                 tooltip="模型/日志/checkpoint 输出目录。\n"
                         "留空默认 models/<profile>/，产物：\n"
                         "  model.onnx / last.pt / metrics.json / train_log.txt / meta.json"),
        FlagSpec("--ui-mode", "choice", default="no-ui",
                 choices=["no-ui", "ui", "both"], group="数据源",
                 help="训练 ui-mode 标注",
                 tooltip="标记此次训练用的是 pre-UI / post-UI 数据。\n"
                         "runtime BCDriver 会校验跟 capture 时一致 —— 防止 no-ui 模型推 post-UI 帧。"),
        FlagSpec("--color", "choice", default="no-ui",
                 choices=["no-ui", "ui"], group="数据源",
                 help="--raw 模式时选哪份 BMP",
                 tooltip="no-ui = BackBuffer.bmp\n"
                         "ui    = BackBufferUI.bmp 优先（不存在 fallback BackBuffer.bmp）\n"
                         "仅 --raw 模式有效。"),

        # ── 模型结构 ─────────────────────────────────────────
        FlagSpec("--backbone", "choice", default="resnet18",
                 choices=["resnet18", "mobilenetv3_small"], group="模型",
                 help="冻结的视觉 backbone",
                 tooltip="resnet18         — 默认；准确率高，推理 ~5ms (cpu)\n"
                         "mobilenetv3_small — 更轻，推理 ~2ms (cpu)；适合实时推理"),
        FlagSpec("--frame-window", "int", default=8, group="模型",
                 help="每个样本的连续帧数",
                 tooltip="每个样本看 T 帧（含当前帧），让模型学时序。\n"
                         "T=8 是默认；T 越大 IO 越重（每 sample 读 T 张图）。"),
        FlagSpec("--input-h", "int", default=144, group="模型",
                 help="resize 后高度",
                 tooltip="输入帧 resize 高度。144 = 1080×0.133。\n"
                         "改尺寸会让 .bc_cache_HxW/ 重建（按 H/W 隔离）。"),
        FlagSpec("--input-w", "int", default=256, group="模型",
                 help="resize 后宽度",
                 tooltip="输入帧 resize 宽度。256 = 1920×0.133。"),

        # ── 训练参数 ─────────────────────────────────────────
        FlagSpec("--epochs", "int", default=20, group="训练",
                 help="训练 epoch 数",
                 tooltip="每个 epoch 完整遍历训练集一次。\n"
                         "default 20 通常足够，过拟合前 val 指标平台期。"),
        FlagSpec("--batch-size", "int", default=16, group="训练",
                 help="batch size",
                 tooltip="每次梯度更新的样本数。\n"
                         "GPU 显存够时调大（5070/12GB 实测 64 安全）→ epoch 更快、训练更稳。"),
        FlagSpec("--num-workers", "int", default=-1, group="训练",
                 help="DataLoader 子进程数",
                 tooltip="-1 = 自动 min(8, cpu//2)\n"
                         "0  = 主线程串行（最慢）\n"
                         "8-12 = GPU 利用率低时调高（典型瓶颈：BMP 解码 + resize）"),
        FlagSpec("--lr", "float", default=3e-4, decimals=6, group="训练",
                 help="learning rate",
                 tooltip="AdamW 学习率。\n"
                         "default 3e-4 是 ResNet18 + 小 batch 的稳妥值。"),
        FlagSpec("--device", "choice", default="cpu",
                 choices=["cpu", "cuda"], group="训练",
                 help="训练设备",
                 tooltip="cpu  — 兜底（很慢）\n"
                         "cuda — 有 NVIDIA GPU 时强烈推荐（10-100× 加速）\n"
                         "选 cuda 但 torch 是 CPU build 时会直接报错退出。"),
        FlagSpec("--recovery-weight", "float", default=2.0, group="训练",
                 help="good_recovery 样本权重（DAgger）",
                 tooltip="demo_quality=3（good_recovery，人工接管帧）的 sample weight。\n"
                         "default 2.0 表示这些纠错样本权重 2× 普通 good 样本。\n"
                         "DAgger 训练才有意义；普通 demo 训练这个值无效。"),
    ],
)


# ── video ─────────────────────────────────────────────────────────────────────


VIDEO = SubcommandSchema(
    name="video",
    help="批量生成游戏目录下所有缺失的 video.mp4 / video_ui.mp4",
    flags=[
        FlagSpec("--game-dir", "path", default="",
                 metavar="DIR", path_kind="optional_dir", group="基础",
                 help="游戏目录",
                 tooltip="dataset-root 下的游戏目录，其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录。\n"
                         "扫整个目录补齐所有缺失的 video.mp4。"),
        FlagSpec("--fps", "float", default=0.0, special_value_text="auto", group="基础",
                 help="编码 fps（0/auto = 自动）",
                 tooltip="auto/0 = 从图像文件名时间戳自动估算（推荐，避免快/慢放）\n"
                         "手动设置 fps 与采集 fps 不一致会导致播放速度异常。"),
        FlagSpec("--mask-ui", "store_true", default=False, group="基础",
                 help="额外生成 video_masked.mp4",
                 tooltip="额外编一份 video_masked.mp4：depth==0 像素置黑（去 UI/sky）。\n"
                         "并存而非替换 video.mp4。"),
    ],
)


# ── pack ──────────────────────────────────────────────────────────────────────


PACK = SubcommandSchema(
    name="pack",
    help="批量打包游戏目录下所有采集会话；已有 dataset.h5 跳过",
    flags=[
        # ── 打包 ─────────────────────────────────────────────
        FlagSpec("--game-dir", "path", default="",
                 metavar="DIR", path_kind="optional_dir", group="打包",
                 help="游戏目录",
                 tooltip="dataset-root 下的游戏目录；扫所有 session 补齐 dataset.h5。"),
        FlagSpec("--color", "choice", default="no-ui",
                 choices=["no-ui", "ui"], group="打包",
                 help="哪种图进 /color",
                 tooltip="no-ui = BackBuffer.png\n"
                         "ui    = BackBufferUI.png 优先（不存在 fallback BackBuffer.png）"),
        FlagSpec("--depth", "bool_optional", default=True, group="打包",
                 help="包含 /depth 数据集",
                 tooltip="把 DepthBuffer.exr 解码进 HDF5 的 /depth 数据集。\n"
                         "BC 训练只用 color 时可关，省空间。"),
        FlagSpec("--normal", "bool_optional", default=False, group="打包",
                 help="包含 /normal 数据集",
                 tooltip="把 NormalBuffer 数据写进 /normal 数据集。\n"
                         "占空间大且 BC 不用，默认关。"),

        # ── 抽检（spot-check）────────────────────────────────
        FlagSpec("--spot-check", "path", default="",
                 metavar="H5_PATH", path_kind="optional_path", group="抽检",
                 help="抽检模式：传 .h5 做完整性检查",
                 tooltip="不打包，仅对已有 dataset.h5 做完整性检查。\n"
                         "抽几帧解码后跟原始 BMP 对比，确认无坏数据。"),
        FlagSpec("--check-frames", "str", default="0,99,499", group="抽检",
                 help="抽检帧索引（逗号分隔）",
                 tooltip="例：0,99,499 抽检第 0/99/499 帧。\n"
                         "仅 --spot-check 模式有效。"),
        FlagSpec("--check-out", "path", default="",
                 path_kind="optional_dir", group="抽检",
                 help="抽检结果输出目录",
                 tooltip="抽检 BMP/depth/normal 落盘到这里，肉眼对比原始数据。\n"
                         "仅 --spot-check 模式有效。"),
    ],
)


SCHEMAS: dict[str, SubcommandSchema] = {
    "launch": LAUNCH,
    "video": VIDEO,
    "pack": PACK,
    "train-bc": TRAIN_BC,
}


# ── 表单值 → CLI argv ─────────────────────────────────────────────────────────


def is_default(spec: FlagSpec, value: Any) -> bool:
    """空字符串当未填；其它按值比对。"""
    if spec.kind in ("str", "path"):
        return (value or "") == (spec.default or "")
    return value == spec.default


def values_to_argv(schema: SubcommandSchema, values: dict[str, Any]) -> list[str]:
    """把表单值列表转 argv 片段（path 类型始终 emit，其它仅含偏离默认值）。"""
    argv: list[str] = []
    for spec in schema.flags:
        v = values.get(spec.cli_key(), spec.default)
        # path 类型：只要非空就 emit（即便等于 spec.default —— 让预览自包含）
        if spec.kind == "path":
            if v:
                argv.extend([spec.name, str(v)])
            continue
        if is_default(spec, v):
            continue

        if spec.kind == "store_true":
            if v:
                argv.append(spec.name)
        elif spec.kind == "bool_optional":
            # argparse.BooleanOptionalAction：True → --flag；False → --no-flag
            if v:
                argv.append(spec.name)
            else:
                argv.append(spec.name.replace("--", "--no-"))
        elif spec.kind == "choice":
            if v:  # 空字符串=未选，跳过
                argv.extend([spec.name, str(v)])
        elif spec.kind in ("str", "path"):
            if v:
                argv.extend([spec.name, str(v)])
        elif spec.kind in ("int", "float"):
            argv.extend([spec.name, str(v)])
    return argv

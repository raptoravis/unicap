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
        FlagSpec("--game-path", "path",
                 default=r"E:\games\ff7remake\End\Binaries\Win64\ff7remake_.exe",
                 path_kind="file",
                 help="游戏 exe 完整路径"),
        FlagSpec("--dataset-root", "path", default=r"D:\unicap_output",
                 path_kind="optional_dir",
                 help="dataset 输出根目录（默认与 tools/capture/config.py:DATASET_ROOT 同步）"),
        FlagSpec("--ui-mode", "choice", default=None,
                 choices=["", "no-ui", "ui", "both"],
                 help="no-ui=只 pre-UI；ui=只 post-UI BB；both=双流；空=按 --auto-play 自动选"),
        FlagSpec("--api", "choice", default="auto",
                 choices=["auto", "dx", "vulkan"],
                 help="渲染后端：auto=按 exe 名启发；dx=DXGI proxy；vulkan=Vulkan layer"),
        FlagSpec("--vk-debug", "store_true", default=False,
                 help="Vulkan：启用 VK_LOADER_DEBUG=layer，写到 %TEMP%/unicap/vk_loader.log"),
        FlagSpec("--hints", "bool_optional", default=True,
                 help="显示 console + addon overlay 操作提示（默认开）"),
        FlagSpec("--force-borderless", "bool_optional", default=True,
                 help="启动后强制 borderless 撑满显示器（避免 DXGI fullscreen 冻结 console）"),
        FlagSpec("--video", "bool_optional", default=False,
                 help="F9 停止后立即生成 video.mp4（默认不生成）"),
        FlagSpec("--capture-duration", "float", default=60.0,
                 metavar="SECONDS",
                 help="单次 capture 时长（秒）；到时自动 roll 新 session；F9 终止整轮。0=不限时"),
        FlagSpec("--mask-ui", "store_true", default=False,
                 help="同时生成 video_masked.mp4（depth==0|>=0.999 像素置黑）"),
        FlagSpec("--pack", "store_true", default=False,
                 help="F9 停止后立即打包 HDF5（默认不打包）"),
        FlagSpec("--color", "choice", default="no-ui",
                 choices=["no-ui", "ui"],
                 help="--pack 时哪种图进 /color：no-ui=BackBuffer.png；ui=BackBufferUI.png 优先"),
        FlagSpec("--normal", "store_true", default=False,
                 help="--pack 时同时打包 /normal（默认不打包）"),
        FlagSpec("--auto-play", "store_true", default=False,
                 help="启用 auto-play bot（F9 停止时一并停）"),
        FlagSpec("--profile", "str", default="",
                 help="auto-play profile 名（profiles/<name>.yaml）；空=按 exe 名 fuzzy match"),
        FlagSpec("--auto-play-debug", "store_true", default=False,
                 help="auto-play 详细 log（每次注入打到 auto_play.log）"),
    ],
)


# ── video ─────────────────────────────────────────────────────────────────────


VIDEO = SubcommandSchema(
    name="video",
    help="批量生成游戏目录下所有缺失的 video.mp4 / video_ui.mp4",
    flags=[
        FlagSpec("--game-dir", "path", default="",
                 metavar="DIR", path_kind="optional_dir",
                 help="dataset-root 下的游戏目录（其下含 <YYYYMMDD_HHMMSS>/frames/ 子目录）"),
        FlagSpec("--fps", "float", default=0.0, special_value_text="auto",
                 help="编码 fps；auto/0 = 从图像文件名时间戳自动估算（推荐，避免快/慢放）"),
        FlagSpec("--mask-ui", "store_true", default=False,
                 help="额外生成 video_masked.mp4：depth==0 像素置黑"),
    ],
)


# ── pack ──────────────────────────────────────────────────────────────────────


PACK = SubcommandSchema(
    name="pack",
    help="批量打包游戏目录下所有采集会话；已有 dataset.h5 跳过",
    flags=[
        FlagSpec("--game-dir", "path", default="",
                 metavar="DIR", path_kind="optional_dir",
                 help="dataset-root 下的游戏目录"),
        FlagSpec("--color", "choice", default="no-ui",
                 choices=["no-ui", "ui"],
                 help="哪种图进 /color"),
        FlagSpec("--depth", "bool_optional", default=True,
                 help="包含 /depth 数据集"),
        FlagSpec("--normal", "bool_optional", default=False,
                 help="包含 /normal 数据集"),
        FlagSpec("--spot-check", "path", default="",
                 metavar="H5_PATH", path_kind="optional_path",
                 help="HDF5 抽检模式：传入 .h5 路径做完整性检查"),
        FlagSpec("--check-frames", "str", default="0,99,499",
                 help="抽检帧索引（逗号分隔）"),
        FlagSpec("--check-out", "path", default="",
                 path_kind="optional_dir",
                 help="抽检结果输出目录"),
    ],
)


SCHEMAS: dict[str, SubcommandSchema] = {
    "launch": LAUNCH,
    "video": VIDEO,
    "pack": PACK,
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

"""Full smoke test — exercise major code paths without a real game."""

import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget

app = QApplication([])
print("=== smoke_full ===", flush=True)

# ── 1. cli_schema → argv 完整往返 ─────────────────────────────────────────────
from unicap_gui.shared.cli_schema import LAUNCH, VIDEO, PACK, values_to_argv

for sch in (LAUNCH, VIDEO, PACK):
    defaults = {f.cli_key(): f.default for f in sch.flags}
    argv = values_to_argv(sch, defaults)
    assert argv == [], f"{sch.name} 全 default 应该 argv=[] 但得 {argv!r}"
print("[1] all-default → empty argv: OK", flush=True)

# 改一些值
v = {f.cli_key(): f.default for f in LAUNCH.flags}
v.update({
    "auto_play": True, "driver": "vlm", "profile": "ff7r",
    "force_borderless": False, "vk_debug": True,
    "capture_duration": 30.0, "vlm_budget_per_hour": 600,
})
argv = values_to_argv(LAUNCH, v)
expected_parts = ["--vk-debug", "--no-force-borderless", "--capture-duration", "30.0",
                   "--auto-play", "--driver", "vlm", "--profile", "ff7r",
                   "--vlm-budget-per-hour", "600"]
assert all(p in argv for p in expected_parts), f"argv 缺关键 flag：{argv!r}"
print(f"[2] mixed values → argv = {argv}", flush=True)

# ── 3. log_tailer regex 正确性 ──────────────────────────────────────────────
from unicap_gui.shared.log_tailer import (
    _RE_VLM_COST, _RE_WATCHDOG, _RE_HEARTBEAT, _RE_ATTACK_HB,
    _RE_RECOVERY_BEGIN,
)
samples = [
    ("[VLM-COST] call#42 t=2.30s in=1024 out=128 cache_r=512", _RE_VLM_COST, "42"),
    ("[WATCHDOG] static-frame 触发 #7 mean=0.0324 moved=6.8% → 注入 recovery (16 步)",
     _RE_WATCHDOG, "7"),
    ("[HEARTBEAT] silent=1.5s → 注入 W 1500ms (heartbeat#3)", _RE_HEARTBEAT, None),
    ("[ATTACK-HB] 注入 attack#1 (period=12.0s)", _RE_ATTACK_HB, None),
]
for line, regex, expected_cap in samples:
    m = regex.search(line)
    assert m, f"regex {regex.pattern!r} 没匹配 {line!r}"
    if expected_cap is not None:
        assert m.group(1) == expected_cap, f"capture got {m.group(1)!r} expected {expected_cap!r}"
# recovery begin 必须独立匹配
assert _RE_RECOVERY_BEGIN.search(samples[1][0]), "recovery_begin 应当匹配 watchdog 触发行"
print("[3] log_tailer regexes: OK", flush=True)

# ── 4. SessionTree 扫描行为 ──────────────────────────────────────────────────
from unicap_gui.widgets.session_tree import SessionTree

tmp = Path(tempfile.mkdtemp(prefix="unicap_gui_smoke_"))
# 构造假的 game-dir：含 3 个 session 各种产物状态
(tmp / "20260101_000000" / "frames").mkdir(parents=True)
(tmp / "20260101_000000" / "video.mp4").touch()
(tmp / "20260101_000000" / "dataset.h5").touch()

(tmp / "20260102_000000" / "frames").mkdir(parents=True)
(tmp / "20260102_000000" / "video.mp4").touch()
# no dataset.h5 → 应该被默认勾选

(tmp / "20260103_000000" / "frames").mkdir(parents=True)
# 缺 video + h5 → 默认勾选

(tmp / "survey").mkdir()  # 应该被排除

tree = SessionTree()
tree.set_game_dir(str(tmp))
selected = tree.selected_session_names()
print(f"[4] sessions in tree (default checked): {selected}", flush=True)
assert "20260101_000000" not in selected, "齐全的 session 不该默认勾选"
assert "20260102_000000" in selected, "缺 dataset.h5 的 session 应默认勾选"
assert "20260103_000000" in selected, "缺 video+h5 的 session 应默认勾选"

# ── 5. AutoPlayPanel profile 扫描 ───────────────────────────────────────────
from unicap_gui.widgets.auto_play_panel import AutoPlayPanel

panel = AutoPlayPanel()
n_profiles = panel._profile_list.count()
print(f"[5] AutoPlayPanel profile 数：{n_profiles}", flush=True)
assert n_profiles >= 4, f"profile 应至少 4 个（_default/ff7r/...）但只有 {n_profiles}"

# ── 6. MainWindow 打开后切换 tab 不崩 ───────────────────────────────────────
from unicap_gui.app import MainWindow

win = MainWindow()
tw = win.findChild(QTabWidget)
for i in range(tw.count()):
    tw.setCurrentIndex(i)
    print(f"[6] 切到 tab #{i} = {tw.tabText(i)} OK", flush=True)

# ── 7. precheck 逻辑 ──────────────────────────────────────────────────────
launch_tab = win._launch
# 故意放一个不存在的 game-path
launch_tab._form.set_values({"game_path": r"X:\definitely_not_real.exe"})
ok, msg = launch_tab._precheck_before_start()
assert not ok, "不存在的 game-path 应预检失败"
assert "不存在" in msg, f"错误信息没含'不存在'：{msg!r}"
print(f"[7a] precheck 拒绝不存在 game-path: '{msg.splitlines()[0]}'", flush=True)

# vlm driver 但 .env 无 KEY
launch_tab._form.set_values({
    "game_path": str(Path(__file__).resolve()),  # 用本文件糊弄存在性
    "auto_play": True, "driver": "vlm",
})
ok, msg = launch_tab._precheck_before_start()
print(f"[7b] vlm without key precheck: ok={ok}", flush=True)
# .env 可能存在或不存在，所以这里只看 message 是否提到 VLM_API_KEY 当 ok=False
if not ok:
    assert "VLM_API_KEY" in msg, f"VLM 错误信息异常：{msg!r}"
    print(f"      msg: '{msg.splitlines()[0]}'", flush=True)

# ── 8. cleanup 临时目录 ──────────────────────────────────────────────────
import shutil
shutil.rmtree(tmp, ignore_errors=True)

print("ALL OK", flush=True)
win.close()
del win

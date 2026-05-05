"""OCR-based dismiss-prompt detector — watchdog's C arm.

Wraps Windows.Media.Ocr (system-bundled, free, en + zh + ja out of the box
on Windows 10+) behind a sync interface. `detect_dismiss_prompt(bgr)` returns
a dismiss key ("M", "ESC", ...) when on-screen text matches a key-hint
pattern like "M Back" / "Press ESC to dismiss" / "按 M 返回"; None otherwise.

Lazy-init: missing winrt → one-time WARN log + arm permanently disabled;
unicap continues working. Install winrt via `uv sync --extra auto-play-ocr`.

Cost per call: 100-500ms on modern CPU. Watchdog runs this every N samples
(not every sample) to keep CPU contention with the game low.
"""

from __future__ import annotations

import asyncio
import logging
import re

import cv2
import numpy as np

log = logging.getLogger("unicap.auto_play")

_engine = None
_init_attempted = False
_init_error: str | None = None

# Dismiss-prompt patterns. Group 1 captures the key. Most→least specific
# ordering so generic patterns don't shadow bracketed/prefixed forms.
_DISMISS_PATTERNS = [
    # "Press M to dismiss" / "Press ESC to continue"
    re.compile(
        r"\bPress\s+([A-Z]|ESC|TAB|SPACE|ENTER|F\d{1,2})\s+to\s+"
        r"(?:Back|Close|Cancel|Skip|Exit|Continue|Dismiss|Return)\b",
        re.IGNORECASE,
    ),
    # "[M] Back" / "(ESC) Close" — bracketed key
    re.compile(
        r"[\[(]\s*([A-Z]+|F\d{1,2})\s*[\])]\s*"
        r"(?:Back|Close|Cancel|Skip|Exit|Continue|Dismiss|Return)\b",
        re.IGNORECASE,
    ),
    # "M Back" / "ESC Close" / "B Cancel" — bare key + verb
    re.compile(
        r"\b([A-Z]|ESC|TAB|SPACE|ENTER|F\d{1,2})\s+"
        r"(?:Back|Close|Cancel|Skip|Exit|Continue|Dismiss|Return)\b",
        re.IGNORECASE,
    ),
    # Chinese: "按 M 返回" / "按ESC关闭"
    re.compile(
        r"按\s*([A-Z]+|F\d{1,2})\s*"
        r"(?:返回|关闭|取消|跳过|退出|继续|完成|确定)",
    ),
]


def _init_engine() -> bool:
    """Lazy init Windows.Media.Ocr engine. Idempotent."""
    global _engine, _init_attempted, _init_error
    if _init_attempted:
        return _engine is not None
    _init_attempted = True
    try:
        import winrt.windows.media.ocr as ocr_ns
    except ImportError as e:
        _init_error = (
            f"winrt 模块缺失 ({e}) — OCR 臂禁用。"
            "装法: uv sync --extra auto-play-ocr"
        )
        log.warning("[OCR] %s", _init_error)
        return False
    try:
        _engine = ocr_ns.OcrEngine.try_create_from_user_profile_languages()
    except Exception as e:
        _init_error = f"OcrEngine 创建异常: {e}"
        log.warning("[OCR] %s", _init_error)
        return False
    if _engine is None:
        _init_error = (
            "OcrEngine.try_create_from_user_profile_languages() 返回 None "
            "— 系统未启用任何 OCR 语言。Settings → Time & Language → 添加 "
            "Language Pack（English / 中文 / 日本語）"
        )
        log.warning("[OCR] %s", _init_error)
        return False
    log.info("[OCR] Windows.Media.Ocr engine 初始化 ok")
    return True


def detect_dismiss_prompt(bgr: np.ndarray) -> str | None:
    """OCR a BGR frame. Return the dismiss key when an on-screen hint
    matches a known pattern; None otherwise.

    Sync / blocking — wraps async winrt behind asyncio.run(). Caller runs
    this from a worker thread (watchdog), where blocking is acceptable."""
    if not _init_engine():
        return None
    if bgr is None or bgr.size == 0:
        return None
    try:
        text = asyncio.run(_ocr_async(bgr))
    except Exception as e:
        log.debug("[OCR] async pipeline 异常: %s", e)
        return None
    if not text:
        return None
    for pat in _DISMISS_PATTERNS:
        m = pat.search(text)
        if m:
            key = m.group(1).upper()
            log.info(
                "[OCR] dismiss-prompt match: key=%s text=%r", key, text[:120],
            )
            return key
    return None


async def _ocr_async(bgr: np.ndarray) -> str:
    """winrt pipeline: BGR ndarray → PNG bytes → InMemoryRandomAccessStream
    → SoftwareBitmap → OcrResult.text."""
    import winrt.windows.graphics.imaging as imaging_ns
    import winrt.windows.storage.streams as streams_ns

    ok, png_buf = cv2.imencode(".png", bgr)
    if not ok:
        return ""
    png_bytes = bytes(png_buf.tobytes())

    stream = streams_ns.InMemoryRandomAccessStream()
    writer = streams_ns.DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await imaging_ns.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    result = await _engine.recognize_async(bitmap)
    return getattr(result, "text", "") or ""


def is_available() -> bool:
    """Cheap check — returns True if engine init has succeeded (or will on
    first call). Used by watchdog to decide whether to schedule OCR ticks."""
    return _init_engine()

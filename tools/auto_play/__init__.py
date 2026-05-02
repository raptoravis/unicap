"""auto_play — bot drivers + input injection for unattended capture.

Public API:
  AutoPlayRunner           — lifecycle orchestrator, called from main.py
  BotDriver, Action, Observation — driver contract + data types
  GameProfile, load_profile — per-game declarative config
  InputBackend             — OS-level input injection (SendInput + ViGEm)
  KeepAliveDriver          — A-layer (no vision) driver
  VLMDriver                — C-layer placeholder (raises until implemented)
"""

from tools.auto_play.driver import Action, BotDriver, Observation
from tools.auto_play.input_backend import InputBackend
from tools.auto_play.keep_alive import KeepAliveDriver
from tools.auto_play.profile import GameProfile, load_profile
from tools.auto_play.runner import AutoPlayRunner
from tools.auto_play.vlm_driver import VLMDriver

__all__ = [
    "Action",
    "AutoPlayRunner",
    "BotDriver",
    "GameProfile",
    "InputBackend",
    "KeepAliveDriver",
    "Observation",
    "VLMDriver",
    "load_profile",
]

# Graph Report - .  (2026-05-04)

## Corpus Check
- 51 files · ~94,879 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 650 nodes · 1019 edges · 45 communities detected
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 170 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Auto-Play Driver ABC|Auto-Play Driver ABC]]
- [[_COMMUNITY_main.py CLI Subcommands|main.py CLI Subcommands]]
- [[_COMMUNITY_Replay Recorder|Replay Recorder]]
- [[_COMMUNITY_Profile Loading|Profile Loading]]
- [[_COMMUNITY_Architecture Overview|Architecture Overview]]
- [[_COMMUNITY_Capture Pipeline & Input Thread|Capture Pipeline & Input Thread]]
- [[_COMMUNITY_Replay-Scene Tests & Bugs|Replay-Scene Tests & Bugs]]
- [[_COMMUNITY_verify_replay Script|verify_replay Script]]
- [[_COMMUNITY_frame_capture C++ Helpers|frame_capture C++ Helpers]]
- [[_COMMUNITY_XInput Gamepad & FF7R Corpus|XInput Gamepad & FF7R Corpus]]
- [[_COMMUNITY_pack_hdf5 Dataset Packer|pack_hdf5 Dataset Packer]]
- [[_COMMUNITY_Sync Match (dHash)|Sync Match (dHash)]]
- [[_COMMUNITY_Replay Mock Backend Tests|Replay Mock Backend Tests]]
- [[_COMMUNITY_Interactive Loop & Hotkeys|Interactive Loop & Hotkeys]]
- [[_COMMUNITY_Window Manager (Borderless)|Window Manager (Borderless)]]
- [[_COMMUNITY_Replay Player Tests|Replay Player Tests]]
- [[_COMMUNITY_Replay Player Core|Replay Player Core]]
- [[_COMMUNITY_Python-C++ Sidecar Protocol|Python<->C++ Sidecar Protocol]]
- [[_COMMUNITY_Build Artifacts & Proposals|Build Artifacts & Proposals]]
- [[_COMMUNITY_Replay-Scene Record Flow|Replay-Scene Record Flow]]
- [[_COMMUNITY_Video & Pack Subcommands|Video & Pack Subcommands]]
- [[_COMMUNITY_Launch & Vulkan Registration|Launch & Vulkan Registration]]
- [[_COMMUNITY_frame_capture Settings (FC_)|frame_capture Settings (FC_*)]]
- [[_COMMUNITY_Pre-UI Capture Path|Pre-UI Capture Path]]
- [[_COMMUNITY_Vulkan Implicit Layer Injection|Vulkan Implicit Layer Injection]]
- [[_COMMUNITY_Timestamp Alignment|Timestamp Alignment]]
- [[_COMMUNITY_Methodology  Agent Guide|Methodology / Agent Guide]]
- [[_COMMUNITY_test_hotkeys Script|test_hotkeys Script]]
- [[_COMMUNITY_Borderless Helpers|Borderless Helpers]]
- [[_COMMUNITY_EXR Save Worker|EXR Save Worker]]
- [[_COMMUNITY_auto_play package init|auto_play package init]]
- [[_COMMUNITY_replay package init|replay package init]]
- [[_COMMUNITY_Render-Pass Hooks|Render-Pass Hooks]]
- [[_COMMUNITY_next_actions docstring|next_actions docstring]]
- [[_COMMUNITY_decision_period docstring|decision_period docstring]]
- [[_COMMUNITY_min_decision_interval docstring|min_decision_interval docstring]]
- [[_COMMUNITY_GAME_PATH constant|GAME_PATH constant]]
- [[_COMMUNITY_on_init_swapchain hook|on_init_swapchain hook]]
- [[_COMMUNITY_on_destroy_swapchain hook|on_destroy_swapchain hook]]
- [[_COMMUNITY_on_destroy_device hook|on_destroy_device hook]]
- [[_COMMUNITY_on_init_effect_runtime hook|on_init_effect_runtime hook]]
- [[_COMMUNITY_on_destroy_effect_runtime hook|on_destroy_effect_runtime hook]]
- [[_COMMUNITY_VLM Driver (C-tier)|VLM Driver (C-tier)]]
- [[_COMMUNITY_Sponsor Profile|Sponsor Profile]]
- [[_COMMUNITY_methodology.md pointer|methodology.md pointer]]

## God Nodes (most connected - your core abstractions)
1. `InputBackend` - 24 edges
2. `Action` - 23 edges
3. `VLMDriver` - 20 edges
4. `load_profile()` - 19 edges
5. `GameProfile` - 18 edges
6. `ReplayRecorder` - 17 edges
7. `AutoPlayRunner` - 15 edges
8. `ReplayPlayer` - 15 edges
9. `MetaModel` - 15 edges
10. `check()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `on_reshade_present` --semantically_similar_to--> `pre-UI capture path`  [INFERRED] [semantically similar]
  reshade-addons/99-frame_capture/frame_capture.cpp → CLAUDE.md
- `test_hotkeys.py F6-F12 diagnostic` --references--> `G-001 Record scene script with sync points`  [INFERRED]
  scripts/test_hotkeys.py → docs/req/replay-scene.md
- `auto-play (无人值守采集)` --conceptually_related_to--> `_run_capture`  [INFERRED]
  CLAUDE.md → main.py
- `pre-UI capture path` --references--> `FC_PreUICapture`  [EXTRACTED]
  CLAUDE.md → reshade-addons/99-frame_capture/frame_capture.cpp
- `t_profile_reserved_keys()` --calls--> `load_profile()`  [INFERRED]
  scripts/verify_replay.py → tools/auto_play/profile.py

## Hyperedges (group relationships)
- **Python<->C++ addon sidecar protocol** — sidecar_fc_output_dir, sidecar_fc_skip_count, sidecar_fc_pass_total, capture_all_run, survey_run, recorder_replayrecorder, replayer_replayplayer [EXTRACTED 0.95]
- **AutoPlayRunner runtime loop** — runner_autoplayrunner, input_backend_inputbackend, keep_alive_keepalivedriver, vlm_driver_vlmdriver, watchdog_staticframewatchdog, driver_action, driver_observation [EXTRACTED 0.95]
- **Replay record/play pipeline** — recorder_replayrecorder, replayer_replayplayer, schema_metamodel, sync_match_wait_for_match, input_backend_inputbackend [EXTRACTED 0.90]
- **Auto-Play feature spec across req/impact/testplan** — req_auto_play_doc, impact_auto_play_doc, testplan_auto_play_doc [EXTRACTED 0.95]
- **Replay-Scene feature spec across req/impact/testplan/feedback** — req_replay_scene_doc, impact_replay_scene_doc, testplan_replay_scene_doc, feedback_replay_scene_session [EXTRACTED 0.95]
- **All built-in profiles implement profile schema** — profiles_default_yaml, profiles_ff7r_yaml, profiles_doom_eternal_yaml, profiles_batman_ak_yaml, concept_game_profile [EXTRACTED 1.00]
- **F6/F7/F8/F9 Hotkey State Machine** — main_hotkey_f6, main_hotkey_f7, main_hotkey_f8, main_hotkey_f9, main_state_idle, main_state_surveying, main_state_capturing, main_state_recording, main_state_replaying, main_interactive_loop [EXTRACTED 0.90]
- **Python<->C++ Sidecar File Protocol** — frame_capture_sidecar_fc_output_dir, frame_capture_sidecar_fc_skip_count, frame_capture_sidecar_fc_pass_total, frame_capture_sidecar_fc_state, frame_capture_sidecar_fc_hints, frame_capture_on_reshade_present, main_set_state, main_write_skip_pulse [EXTRACTED 1.00]
- **CMake Build Targets** — cmakelists_target_reshade_core, cmakelists_target_frame_capture, cmakelists_target_shaders, cmakelists_artifact_dxgi_dll, cmakelists_artifact_unicap64_dll, cmakelists_artifact_unicap64_json, cmakelists_artifact_frame_capture_addon [EXTRACTED 1.00]

## Communities (48 total, 16 thin omitted)

### Community 0 - "Auto-Play Driver ABC"
Cohesion: 0.05
Nodes (41): ABC, Action, BotDriver, Observation, BotDriver contract — what every driver exposes.  Drivers turn an `Observation` (, One unit of input injection.      kind=='key':     payload = {'vk': 'W', 'event', What the driver sees on each decision tick.      frame_bgr is the latest BackBuf, Contract: A subclass produces Actions; the runner injects them. (+33 more)

### Community 1 - "main.py CLI Subcommands"
Cohesion: 0.05
Nodes (66): _apply_ui_mask_bgr(), _bmp_ts_ms(), cmd_deploy(), cmd_launch(), cmd_pack(), cmd_video(), _depth_path_for(), _drain_keys() (+58 more)

### Community 2 - "Replay Recorder"
Cohesion: 0.06
Nodes (32): _diff_events(), _is_pressed(), _Point, ReplayRecorder — polls input state, emits diff events, handles F6/F7.  Polling c, High bit of GetKeyboardState byte = currently down., Compare two snapshots, emit minimal event list., Records a scene script. Lifecycle: __init__ → start() → wait_until_done() → clos, Block until F7 pressed (or external stop()). Returns; caller calls save() then c (+24 more)

### Community 3 - "Profile Loading"
Cohesion: 0.08
Nodes (33): list_profiles(), load_profile(), _profiles_dir(), GameProfile — declarative per-game config loaded from profiles/*.yaml.  Profile, Load `<profiles_dir>/<name>.yaml`. With fallback=True, fuzzy-match the     name, _read_profile_file(), _validate_profile(), create_driver() (+25 more)

### Community 4 - "Architecture Overview"
Cohesion: 0.07
Nodes (44): AutoPlayRunner orchestrator, BotDriver ABC, GameProfile YAML, InputBackend (SendInput + ViGEm), KeepAliveDriver, ReplayPlayer, StaticFrameWatchdog, VLMDriver (C-layer) (+36 more)

### Community 5 - "Capture Pipeline & Input Thread"
Cohesion: 0.07
Nodes (41): capture_all.run, _thread_input, DATASET_ROOT, Action, BotDriver, Observation, _GAMEPAD_BUTTON_MAP, InputBackend (+33 more)

### Community 6 - "Replay-Scene Tests & Bugs"
Cohesion: 0.07
Nodes (31): ReplayRecorder, sync_match dHash + hamming, BUG-001 Launch help omits F7, BUG-002 Scene validation after game launch, BUG-003 Empty scene name silently ignored, BUG-004 Scene name allows .. traversal, FEAT-001 list-scenes helper, Auto-Test Session: replay-scene v1.0 (+23 more)

### Community 7 - "verify_replay Script"
Cohesion: 0.07
Nodes (26): main(), verify_replay — offline sanity checks for tools/replay/.  Run by sponsor:     uv, --record-scene + --auto-play must NOT be rejected by mutex (it's a     valid com, Same: --replay-scene + --auto-play is the killer unattended combo., BUG-002 fix: replay precheck rejects nonexistent scene before game launch., BUG-002 fix: record precheck rejects already-populated scene_dir., BUG-002 fix: record precheck passes for fresh / non-existent scene_dir., --auto-capture sets auto_capture_first=True; loop's first iteration     must ski (+18 more)

### Community 8 - "frame_capture C++ Helpers"
Cohesion: 0.11
Nodes (17): decode_to_rgba8(), DllMain(), draw_settings_overlay(), drawItem(), fc_copy_rt_at_bind(), fc_find_export_tex(), hdr_to_u8(), on_begin_render_effects() (+9 more)

### Community 9 - "XInput Gamepad & FF7R Corpus"
Cohesion: 0.12
Nodes (22): main(), _parse_xinput(), POINT, FF7 Remake 采集管线 — 一键启动 同时运行：输入录制（120Hz）+ 进度监控 addon 通过 FC_TargetFPS 自动定时采集，通过, 采集帧 + 输入。停止条件（任一触发即停）：       - 外部 stop_event 被 set（F9 热键）       - duration 秒数到, run(), _thread_input(), XINPUT_GAMEPAD (+14 more)

### Community 10 - "pack_hdf5 Dataset Packer"
Cohesion: 0.12
Nodes (24): _encode_gamepad(), _load_bmp(), _load_depth(), load_inputs(), _load_normal(), main(), nearest_input(), pack() (+16 more)

### Community 11 - "Sync Match (dHash)"
Cohesion: 0.17
Nodes (15): dhash(), hamming(), MatchResult, dHash + hamming + wait_for_match — visual sync-point matching.  dHash chosen ove, Poll frames_dir for a frame matching ref_path within `threshold` hamming distanc, 64-bit difference hash. Accepts BGR uint8 ndarray; resizes to 9x8 grayscale., Population count of XOR — 0 to 64 for 64-bit hashes., Find newest *BackBuffer.bmp older than min_age_s (avoid mid-write reads).      M (+7 more)

### Community 12 - "Replay Mock Backend Tests"
Cohesion: 0.14
Nodes (12): iter_events(), Stream events from script.jsonl. Validates t_rel monotonic; raises on regression, Start recorder briefly with no real input → save() produces empty-ish files., close() must clear fc_output_dir.txt and rmtree scratch., New 'down' / 'up' mouse ops do not raise on construction., E2E-1 + E2E-2 (offline): recorder writes script → player reads + completes., t_e2e_record_then_replay_round_trip(), t_inputbackend_mouse_op_extension() (+4 more)

### Community 13 - "Interactive Loop & Hotkeys"
Cohesion: 0.18
Nodes (14): auto-play (无人值守采集), fc_output_dir.txt, 杀手组合 (replay+auto-play+auto-capture), F8 hotkey (start capture), F9 hotkey (stop), _interactive_loop, _load_recommended_skip, _run_capture (+6 more)

### Community 14 - "Window Manager (Borderless)"
Cohesion: 0.19
Nodes (12): _find_main_window(), force_borderless(), force_borderless_async(), _monitor_rect(), _MONITORINFO, _query_image_basename(), Force borderless windowed mode — 避免 DXGI fullscreen-exclusive 让 DWM 暂停 后台 consol, Return (x, y, width, height) of the monitor containing hwnd (handles multi-monit (+4 more)

### Community 15 - "Replay Player Tests"
Cohesion: 0.19
Nodes (12): _make_dummy_scene(), _MockBackend, Build a minimal scene_dir + matching scratch with a 'live' BMP., Stand-in for InputBackend — records every inject() call., Sync miss → paused → simulated 'R' → continues to completion., Sync miss → paused → simulated 'Q' → user_abort, exit 2., Different window size → warn once + scaled mouse_move., t_player_no_sync_happy() (+4 more)

### Community 16 - "Replay Player Core"
Cohesion: 0.21
Nodes (8): get_screen_center(), ReplayPlayer — replay script.jsonl events through InputBackend with sync waiting, Block until user decides R(esume) or Q(uit). 'R' default., Replay one scene. Public surface: __init__ → run() → ReplayResult., scene_dir: _scenes/<name>/         sync_scratch_dir: where addon writes BMPs dur, recenter_cursor(), ReplayPlayer, ReplayResult

### Community 17 - "Python<->C++ Sidecar Protocol"
Cohesion: 0.22
Nodes (13): Python<->C++ sidecar protocol, dist/frame_capture.addon, frame_capture (build target), shaders (build target), on_reshade_present, fc_hints.txt, fc_pass_total.txt, fc_skip_count.txt (+5 more)

### Community 18 - "Build Artifacts & Proposals"
Cohesion: 0.18
Nodes (10): dist/dxgi.dll (ReShade core), frame_capture.addon, unicap.exe (Nuitka standalone), FF7 Remake 逐帧数据采集方案调研报告, Proposal 3: 自研 DX11 Proxy DLL, Proposal 2: RenderDoc + UE4 console, Proposal 1: ReShade + FrameCapture Addon, UE4 Reverse-Z depth note (+2 more)

### Community 19 - "Replay-Scene Record Flow"
Cohesion: 0.25
Nodes (8): replay-scene v1.0, replay-scene v1.0 handoff, cmd_scenes, F6 hotkey (record sync), F7 hotkey (record stop), _run_record, state: recording, scenes (subcommand)

### Community 20 - "Video & Pack Subcommands"
Cohesion: 0.25
Nodes (8): --mask-ui depth-based UI mask, _apply_ui_mask_bgr, cmd_pack, cmd_video, main, _make_video, pack (subcommand), video (subcommand)

### Community 21 - "Launch & Vulkan Registration"
Cohesion: 0.25
Nodes (8): --force-borderless (avoid DWM freeze), cmd_deploy, cmd_launch, _precheck_scene, launch (subcommand), _validate_launch_args, _vk_clean_stale_entries, _vk_unregister_layer

### Community 22 - "frame_capture Settings (FC_*)"
Cohesion: 0.29
Nodes (7): on_init_device, FC_BothCapture, FC_EnableCapture, FC_ExportDepth, FC_PreUICapture, FC_PreUISkipCount, FC_TargetFPS

### Community 23 - "Pre-UI Capture Path"
Cohesion: 0.53
Nodes (6): pre-UI capture path, fc_copy_rt_at_bind, g_pre_ui_staging, on_begin_render_pass, on_bind_rts_dsv, pre-UI reverse-skip math

### Community 24 - "Vulkan Implicit Layer Injection"
Cohesion: 0.4
Nodes (6): Vulkan implicit layer injection, dist/dxgi.dll, dist/UniCap64.dll, dist/UniCap64.json, reshade_core (build target), _vk_register_layer

### Community 25 - "Timestamp Alignment"
Cohesion: 0.5
Nodes (4): nearest_input, pack_hdf5.pack, scan_frames, _to_utc_ns

### Community 26 - "Methodology / Agent Guide"
Cohesion: 0.67
Nodes (4): 多 Agent 并行开发实操手册, 四种并行模式, 三把钥匙 (需求对齐/TPDD/Skill), TPDD 测试计划驱动开发

### Community 28 - "Borderless Helpers"
Cohesion: 0.67
Nodes (3): _find_main_window, force_borderless, force_borderless_async

### Community 29 - "EXR Save Worker"
Cohesion: 0.67
Nodes (3): save_worker_fn, SaveEXR, SaveTask

## Knowledge Gaps
- **222 isolated node(s):** `Read [project].version from pyproject.toml. Source mode reads repo     pyprojec`, `Write current high-level state to fc_state.txt for the addon overlay.`, `Edge-detected wait for any of `vks`. Returns the pressed VK, or None on abort.`, `Background thread that sets stop_event when F9 is pressed.     Returns a quit-e`, `UE4 has a launcher exe + nested actual game at <Project>\\Binaries\\Win64\\.` (+217 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Action` connect `Auto-Play Driver ABC` to `Replay Player Core`, `Profile Loading`, `Replay Mock Backend Tests`, `Replay Player Tests`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `BudgetExhausted` connect `Auto-Play Driver ABC` to `pack_hdf5 Dataset Packer`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `InputBackend` connect `Auto-Play Driver ABC` to `main.py CLI Subcommands`, `Profile Loading`, `Replay Mock Backend Tests`, `Replay Player Tests`, `Replay Player Core`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `InputBackend` (e.g. with `_MockBackend` and `Action`) actually correct?**
  _`InputBackend` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `Action` (e.g. with `_MockBackend` and `GameProfile`) actually correct?**
  _`Action` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `VLMDriver` (e.g. with `AutoPlayRunner` and `Action`) actually correct?**
  _`VLMDriver` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `load_profile()` (e.g. with `_start_auto_play()` and `_run_replay()`) actually correct?**
  _`load_profile()` has 15 INFERRED edges - model-reasoned connections that need verification._
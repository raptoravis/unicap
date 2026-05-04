# Graph Report - .  (2026-05-04)

## Corpus Check
- 51 files · ~98,377 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 650 nodes · 962 edges · 49 communities detected
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 113 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_main.py CLI Subcommands|main.py CLI Subcommands]]
- [[_COMMUNITY_Auto-Play Driver Contract|Auto-Play Driver Contract]]
- [[_COMMUNITY_Architecture Overview|Architecture Overview]]
- [[_COMMUNITY_Capture Pipeline & Input Thread|Capture Pipeline & Input Thread]]
- [[_COMMUNITY_Replay-Scene Tests & Bugs|Replay-Scene Tests & Bugs]]
- [[_COMMUNITY_Replay Recorder|Replay Recorder]]
- [[_COMMUNITY_verify_replay Script|verify_replay Script]]
- [[_COMMUNITY_frame_capture C++ Helpers|frame_capture C++ Helpers]]
- [[_COMMUNITY_VLM Cost Tracker|VLM Cost Tracker]]
- [[_COMMUNITY_XInput Gamepad & FF7R Corpus|XInput Gamepad & FF7R Corpus]]
- [[_COMMUNITY_pack_hdf5 Dataset Packer|pack_hdf5 Dataset Packer]]
- [[_COMMUNITY_InputBackend Internals|InputBackend Internals]]
- [[_COMMUNITY_Replay Schema|Replay Schema]]
- [[_COMMUNITY_Sync Match (dHash)|Sync Match (dHash)]]
- [[_COMMUNITY_Window Manager (Borderless)|Window Manager (Borderless)]]
- [[_COMMUNITY_Replay Player Core|Replay Player Core]]
- [[_COMMUNITY_Pre-UI Capture Path|Pre-UI Capture Path]]
- [[_COMMUNITY_Sidecar Protocol & EXR Save|Sidecar Protocol & EXR Save]]
- [[_COMMUNITY_Interactive Loop & Hotkeys|Interactive Loop & Hotkeys]]
- [[_COMMUNITY_Build Artifacts & Proposals|Build Artifacts & Proposals]]
- [[_COMMUNITY_BotDriver ABC Methods|BotDriver ABC Methods]]
- [[_COMMUNITY_Replay Player Tests|Replay Player Tests]]
- [[_COMMUNITY_Video  Pack  Scenes Subcommands|Video / Pack / Scenes Subcommands]]
- [[_COMMUNITY_Recorder Tests|Recorder Tests]]
- [[_COMMUNITY_InputBackend Mocks & E2E|InputBackend Mocks & E2E]]
- [[_COMMUNITY_Vulkan Implicit Layer Injection|Vulkan Implicit Layer Injection]]
- [[_COMMUNITY_Replay-Scene Record Flow|Replay-Scene Record Flow]]
- [[_COMMUNITY_Auto-Play Unattended Capture|Auto-Play Unattended Capture]]
- [[_COMMUNITY_Timestamp Alignment|Timestamp Alignment]]
- [[_COMMUNITY_Survey Loop|Survey Loop]]
- [[_COMMUNITY_Methodology  Agent Guide|Methodology / Agent Guide]]
- [[_COMMUNITY_test_hotkeys Script|test_hotkeys Script]]
- [[_COMMUNITY_Borderless Helpers|Borderless Helpers]]
- [[_COMMUNITY_CMake Build Targets|CMake Build Targets]]
- [[_COMMUNITY_auto_play package init|auto_play package init]]
- [[_COMMUNITY_replay package init|replay package init]]
- [[_COMMUNITY_Render-Pass Hooks|Render-Pass Hooks]]
- [[_COMMUNITY_next_actions docstring|next_actions docstring]]
- [[_COMMUNITY_decision_period docstring|decision_period docstring]]
- [[_COMMUNITY_min_decision_interval docstring|min_decision_interval docstring]]
- [[_COMMUNITY_on_init_swapchain hook|on_init_swapchain hook]]
- [[_COMMUNITY_on_destroy_swapchain hook|on_destroy_swapchain hook]]
- [[_COMMUNITY_on_destroy_device hook|on_destroy_device hook]]
- [[_COMMUNITY_on_init_effect_runtime hook|on_init_effect_runtime hook]]
- [[_COMMUNITY_on_destroy_effect_runtime hook|on_destroy_effect_runtime hook]]
- [[_COMMUNITY_GAME_PATH constant|GAME_PATH constant]]
- [[_COMMUNITY_VLM Driver (C-tier)|VLM Driver (C-tier)]]
- [[_COMMUNITY_methodology.md pointer|methodology.md pointer]]
- [[_COMMUNITY_Sponsor Profile|Sponsor Profile]]

## God Nodes (most connected - your core abstractions)
1. `load_profile()` - 19 edges
2. `InputBackend` - 17 edges
3. `ReplayRecorder` - 16 edges
4. `VLMDriver` - 15 edges
5. `check()` - 14 edges
6. `Requirements: 自动玩游戏机制` - 14 edges
7. `cmd_launch()` - 13 edges
8. `ReplayPlayer` - 13 edges
9. `Requirements: replay-scene` - 13 edges
10. `_run_replay()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `on_reshade_present` --semantically_similar_to--> `pre-UI capture path`  [INFERRED] [semantically similar]
  reshade-addons/99-frame_capture/frame_capture.cpp → CLAUDE.md
- `auto-play (无人值守采集)` --conceptually_related_to--> `_run_capture`  [INFERRED]
  CLAUDE.md → main.py
- `杀手组合 (replay+auto-play+auto-capture)` --rationale_for--> `_run_replay`  [EXTRACTED]
  HANDOFF.md → main.py
- `frame_capture (build target)` --references--> `on_reshade_present`  [EXTRACTED]
  CMakeLists.txt → reshade-addons/99-frame_capture/frame_capture.cpp
- `test_hotkeys.py F6-F12 diagnostic` --references--> `G-001 Record scene script with sync points`  [INFERRED]
  scripts/test_hotkeys.py → docs/req/replay-scene.md

## Hyperedges (group relationships)
- **F6/F7/F8/F9 Hotkey State Machine** — main_hotkey_f6, main_hotkey_f7, main_hotkey_f8, main_hotkey_f9, main_state_idle, main_state_surveying, main_state_capturing, main_state_recording, main_state_replaying, main_interactive_loop [EXTRACTED 0.90]
- **Python<->C++ Sidecar File Protocol** — frame_capture_sidecar_fc_output_dir, frame_capture_sidecar_fc_skip_count, frame_capture_sidecar_fc_pass_total, frame_capture_sidecar_fc_state, frame_capture_sidecar_fc_hints, frame_capture_on_reshade_present, main_set_state, main_write_skip_pulse [EXTRACTED 1.00]
- **AutoPlayRunner runtime loop** — runner_autoplayrunner, input_backend_inputbackend, keep_alive_keepalivedriver, vlm_driver_vlmdriver, watchdog_staticframewatchdog, driver_action, driver_observation [EXTRACTED 0.95]
- **Python<->C++ addon sidecar protocol** — sidecar_fc_output_dir, sidecar_fc_skip_count, sidecar_fc_pass_total, capture_all_run, survey_run, recorder_replayrecorder, replayer_replayplayer [EXTRACTED 0.95]
- **Replay record/play pipeline** — recorder_replayrecorder, replayer_replayplayer, schema_metamodel, sync_match_wait_for_match, input_backend_inputbackend [EXTRACTED 0.90]
- **CMake Build Targets** — cmakelists_target_reshade_core, cmakelists_target_frame_capture, cmakelists_target_shaders, cmakelists_artifact_dxgi_dll, cmakelists_artifact_unicap64_dll, cmakelists_artifact_unicap64_json, cmakelists_artifact_frame_capture_addon [EXTRACTED 1.00]
- **Auto-Play feature spec across req/impact/testplan** — req_auto_play_doc, impact_auto_play_doc, testplan_auto_play_doc [EXTRACTED 0.95]
- **Replay-Scene feature spec across req/impact/testplan/feedback** — req_replay_scene_doc, impact_replay_scene_doc, testplan_replay_scene_doc, feedback_replay_scene_session [EXTRACTED 0.95]
- **All built-in profiles implement profile schema** — profiles_default_yaml, profiles_ff7r_yaml, profiles_doom_eternal_yaml, profiles_batman_ak_yaml, concept_game_profile [EXTRACTED 1.00]

## Communities (52 total, 16 thin omitted)

### Community 0 - "main.py CLI Subcommands"
Cohesion: 0.05
Nodes (66): _apply_ui_mask_bgr(), _bmp_ts_ms(), cmd_deploy(), cmd_launch(), cmd_pack(), cmd_video(), _depth_path_for(), _drain_keys() (+58 more)

### Community 1 - "Auto-Play Driver Contract"
Cohesion: 0.05
Nodes (48): Action, Observation, One unit of input injection.      kind=='key':     payload = {'vk': 'W', 'event', What the driver sees on each decision tick.      frame_bgr is the latest BackBuf, KeepAliveDriver, _press_control(), KeepAliveDriver — A-layer driver, no vision, follows profile sequence.  Also exp, No-vision bot. Outputs Actions per profile.keep_alive.sequence. (+40 more)

### Community 2 - "Architecture Overview"
Cohesion: 0.07
Nodes (44): AutoPlayRunner orchestrator, BotDriver ABC, GameProfile YAML, InputBackend (SendInput + ViGEm), KeepAliveDriver, ReplayPlayer, StaticFrameWatchdog, VLMDriver (C-layer) (+36 more)

### Community 3 - "Capture Pipeline & Input Thread"
Cohesion: 0.07
Nodes (41): capture_all.run, _thread_input, DATASET_ROOT, Action, BotDriver, Observation, _GAMEPAD_BUTTON_MAP, InputBackend (+33 more)

### Community 4 - "Replay-Scene Tests & Bugs"
Cohesion: 0.07
Nodes (31): ReplayRecorder, sync_match dHash + hamming, BUG-001 Launch help omits F7, BUG-002 Scene validation after game launch, BUG-003 Empty scene name silently ignored, BUG-004 Scene name allows .. traversal, FEAT-001 list-scenes helper, Auto-Test Session: replay-scene v1.0 (+23 more)

### Community 5 - "Replay Recorder"
Cohesion: 0.09
Nodes (17): _diff_events(), _is_pressed(), _Point, ReplayRecorder — polls input state, emits diff events, handles F6/F7.  Polling c, High bit of GetKeyboardState byte = currently down., Compare two snapshots, emit minimal event list., Records a scene script. Lifecycle: __init__ → start() → wait_until_done() → clos, Block until F7 pressed (or external stop()). Returns; caller calls save() then c (+9 more)

### Community 6 - "verify_replay Script"
Cohesion: 0.07
Nodes (26): main(), verify_replay — offline sanity checks for tools/replay/.  Run by sponsor:     uv, --record-scene + --auto-play must NOT be rejected by mutex (it's a     valid com, Same: --replay-scene + --auto-play is the killer unattended combo., BUG-002 fix: replay precheck rejects nonexistent scene before game launch., BUG-002 fix: record precheck rejects already-populated scene_dir., BUG-002 fix: record precheck passes for fresh / non-existent scene_dir., --auto-capture sets auto_capture_first=True; loop's first iteration     must ski (+18 more)

### Community 7 - "frame_capture C++ Helpers"
Cohesion: 0.11
Nodes (17): decode_to_rgba8(), DllMain(), draw_settings_overlay(), drawItem(), fc_copy_rt_at_bind(), fc_find_export_tex(), hdr_to_u8(), on_begin_render_effects() (+9 more)

### Community 8 - "VLM Cost Tracker"
Cohesion: 0.11
Nodes (9): BudgetExhausted, _BudgetTracker, _CallStats, VLMDriver — C-layer (vision-language model brain).  Subscribes to BackBuffer.bmp, Per-hour call cap. Thread-safe., OpenAI-compatible vision-language model driver. Configuration comes     from VLM, Read latest BackBuffer.bmp from frames_dir.          Mirrors watchdog's read pat, Raised by next_actions() when the per-hour cap is hit, or when     VLM_API_KEY / (+1 more)

### Community 9 - "XInput Gamepad & FF7R Corpus"
Cohesion: 0.12
Nodes (22): main(), _parse_xinput(), POINT, FF7 Remake 采集管线 — 一键启动 同时运行：输入录制（120Hz）+ 进度监控 addon 通过 FC_TargetFPS 自动定时采集，通过, 采集帧 + 输入。停止条件（任一触发即停）：       - 外部 stop_event 被 set（F9 热键）       - duration 秒数到, run(), _thread_input(), XINPUT_GAMEPAD (+14 more)

### Community 10 - "pack_hdf5 Dataset Packer"
Cohesion: 0.12
Nodes (24): _encode_gamepad(), _load_bmp(), _load_depth(), load_inputs(), _load_normal(), main(), nearest_input(), pack() (+16 more)

### Community 11 - "InputBackend Internals"
Cohesion: 0.16
Nodes (11): _HardwareInput, _Input, InputBackend, _InputUnion, _KeybdInput, _MouseInput, InputBackend — OS-level input injection.  Combines two channels:   - keyboard /, OS-level input injector. One instance per AutoPlayRunner. (+3 more)

### Community 12 - "Replay Schema"
Cohesion: 0.16
Nodes (15): Write script.jsonl + meta.json. Returns scene_dir., load_meta(), MetaModel, script.jsonl event types + meta.json schema + read/write helpers.  Forward compa, meta.json structure. `syncs` is per-sync-id overrides for thresholds., Raise ValueError listing missing fields. Unknown fields are accepted (forward co, validate_meta(), write_meta() (+7 more)

### Community 13 - "Sync Match (dHash)"
Cohesion: 0.17
Nodes (15): dhash(), hamming(), MatchResult, dHash + hamming + wait_for_match — visual sync-point matching.  dHash chosen ove, Poll frames_dir for a frame matching ref_path within `threshold` hamming distanc, 64-bit difference hash. Accepts BGR uint8 ndarray; resizes to 9x8 grayscale., Population count of XOR — 0 to 64 for 64-bit hashes., Find newest *BackBuffer.bmp older than min_age_s (avoid mid-write reads).      M (+7 more)

### Community 14 - "Window Manager (Borderless)"
Cohesion: 0.19
Nodes (12): _find_main_window(), force_borderless(), force_borderless_async(), _monitor_rect(), _MONITORINFO, _query_image_basename(), Force borderless windowed mode — 避免 DXGI fullscreen-exclusive 让 DWM 暂停 后台 consol, Return (x, y, width, height) of the monitor containing hwnd (handles multi-monit (+4 more)

### Community 15 - "Replay Player Core"
Cohesion: 0.21
Nodes (8): get_screen_center(), ReplayPlayer — replay script.jsonl events through InputBackend with sync waiting, Block until user decides R(esume) or Q(uit). 'R' default., Replay one scene. Public surface: __init__ → run() → ReplayResult., scene_dir: _scenes/<name>/         sync_scratch_dir: where addon writes BMPs dur, recenter_cursor(), ReplayPlayer, ReplayResult

### Community 16 - "Pre-UI Capture Path"
Cohesion: 0.19
Nodes (13): pre-UI capture path, fc_copy_rt_at_bind, g_pre_ui_staging, on_begin_render_pass, on_bind_rts_dsv, on_init_device, pre-UI reverse-skip math, FC_BothCapture (+5 more)

### Community 17 - "Sidecar Protocol & EXR Save"
Cohesion: 0.22
Nodes (13): Python<->C++ sidecar protocol, on_reshade_present, save_worker_fn, SaveEXR, SaveTask, fc_hints.txt, fc_pass_total.txt, fc_skip_count.txt (+5 more)

### Community 18 - "Interactive Loop & Hotkeys"
Cohesion: 0.17
Nodes (13): --force-borderless (avoid DWM freeze), cmd_deploy, cmd_launch, F8 hotkey (start capture), _interactive_loop, _load_recommended_skip, _precheck_scene, _run_replay (+5 more)

### Community 19 - "Build Artifacts & Proposals"
Cohesion: 0.18
Nodes (10): dist/dxgi.dll (ReShade core), frame_capture.addon, unicap.exe (Nuitka standalone), FF7 Remake 逐帧数据采集方案调研报告, Proposal 3: 自研 DX11 Proxy DLL, Proposal 2: RenderDoc + UE4 console, Proposal 1: ReShade + FrameCapture Addon, UE4 Reverse-Z depth note (+2 more)

### Community 20 - "BotDriver ABC Methods"
Cohesion: 0.2
Nodes (6): ABC, BotDriver, BotDriver contract — what every driver exposes.  Drivers turn an `Observation` (, Contract: A subclass produces Actions; the runner injects them., Optional one-time hook before the first next_actions call., Optional cleanup hook called once during runner.stop().

### Community 21 - "Replay Player Tests"
Cohesion: 0.24
Nodes (10): _make_dummy_scene(), _MockBackend, Build a minimal scene_dir + matching scratch with a 'live' BMP., Stand-in for InputBackend — records every inject() call., Sync miss → paused → simulated 'R' → continues to completion., Sync miss → paused → simulated 'Q' → user_abort, exit 2., t_player_no_sync_happy(), t_player_sync_match() (+2 more)

### Community 22 - "Video / Pack / Scenes Subcommands"
Cohesion: 0.2
Nodes (10): --mask-ui depth-based UI mask, _apply_ui_mask_bgr, cmd_pack, cmd_scenes, cmd_video, main, _make_video, pack (subcommand) (+2 more)

### Community 23 - "Recorder Tests"
Cohesion: 0.25
Nodes (8): iter_events(), Stream events from script.jsonl. Validates t_rel monotonic; raises on regression, Start recorder briefly with no real input → save() produces empty-ish files., t_iter_events_t_rel_regression(), t_iter_events_unknown_skip(), t_recorder_smoke_save(), cmd_scenes(), List recorded replay scenes under <game_dir>/_scenes/.

### Community 24 - "InputBackend Mocks & E2E"
Cohesion: 0.25
Nodes (6): close() must clear fc_output_dir.txt and rmtree scratch., New 'down' / 'up' mouse ops do not raise on construction., E2E-1 + E2E-2 (offline): recorder writes script → player reads + completes., t_e2e_record_then_replay_round_trip(), t_inputbackend_mouse_op_extension(), t_recorder_sidecar_cleanup()

### Community 25 - "Vulkan Implicit Layer Injection"
Cohesion: 0.4
Nodes (6): Vulkan implicit layer injection, dist/dxgi.dll, dist/UniCap64.dll, dist/UniCap64.json, reshade_core (build target), _vk_register_layer

### Community 26 - "Replay-Scene Record Flow"
Cohesion: 0.33
Nodes (6): replay-scene v1.0, replay-scene v1.0 handoff, F6 hotkey (record sync), F7 hotkey (record stop), _run_record, state: recording

### Community 27 - "Auto-Play Unattended Capture"
Cohesion: 0.4
Nodes (5): auto-play (无人值守采集), fc_output_dir.txt, 杀手组合 (replay+auto-play+auto-capture), _run_capture, state: capturing

### Community 28 - "Timestamp Alignment"
Cohesion: 0.5
Nodes (4): nearest_input, pack_hdf5.pack, scan_frames, _to_utc_ns

### Community 29 - "Survey Loop"
Cohesion: 0.5
Nodes (4): F9 hotkey (stop), _run_survey, _spawn_f9_watcher, state: surveying

### Community 30 - "Methodology / Agent Guide"
Cohesion: 0.67
Nodes (4): 多 Agent 并行开发实操手册, 四种并行模式, 三把钥匙 (需求对齐/TPDD/Skill), TPDD 测试计划驱动开发

### Community 32 - "Borderless Helpers"
Cohesion: 0.67
Nodes (3): _find_main_window, force_borderless, force_borderless_async

### Community 33 - "CMake Build Targets"
Cohesion: 0.67
Nodes (3): dist/frame_capture.addon, frame_capture (build target), shaders (build target)

## Knowledge Gaps
- **224 isolated node(s):** `Read [project].version from pyproject.toml. Source mode reads repo     pyprojec`, `Write current high-level state to fc_state.txt for the addon overlay.`, `Edge-detected wait for any of `vks`. Returns the pressed VK, or None on abort.`, `Background thread that sets stop_event when F9 is pressed.     Returns a quit-e`, `UE4 has a launcher exe + nested actual game at <Project>\\Binaries\\Win64\\.` (+219 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_profile()` connect `Auto-Play Driver Contract` to `main.py CLI Subcommands`, `InputBackend Mocks & E2E`, `verify_replay Script`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `VLMDriver` connect `VLM Cost Tracker` to `Auto-Play Driver Contract`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `_run_replay()` connect `main.py CLI Subcommands` to `Auto-Play Driver Contract`, `InputBackend Internals`, `Replay Player Core`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `load_profile()` (e.g. with `_start_auto_play()` and `_run_replay()`) actually correct?**
  _`load_profile()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `InputBackend` (e.g. with `_run_replay()` and `cap_input_backend()`) actually correct?**
  _`InputBackend` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `ReplayRecorder` (e.g. with `_run_record()` and `t_recorder_smoke_save()`) actually correct?**
  _`ReplayRecorder` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `VLMDriver` (e.g. with `cap_vlm_driver()` and `e2e_3_vlm_driver_budget_fallback()`) actually correct?**
  _`VLMDriver` has 3 INFERRED edges - model-reasoned connections that need verification._
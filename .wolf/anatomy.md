# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-05-08T09:15:31.860Z
> Files: 514 tracked | Anatomy hits: 0 | Misses: 0

## ./

- `.gitignore` — Git ignore rules (~182 tok)
- `.graphifyignore` — .graphifyignore (~39 tok)
- `.python-version` (~2 tok)
- `CLAUDE.md` — OpenWolf (~4835 tok)
- `CMakeLists.txt` — CMake build configuration (~1371 tok)
- `HANDOFF.md` — Handoff: 打包 unicap CLI + GUI 双 standalone exe (~3303 tok)
- `main.py` — URL configuration (~15639 tok)
- `pyproject.toml` — Python project configuration (~543 tok)
- `README.md` — Project documentation (~7 tok)
- `USER.md` — 项目人类赞助者（Sponsor）档案 (~172 tok)

## .claude/

- `settings.json` (~640 tok)
- `settings.local.json` (~132 tok)

## .claude/rules/

- `openwolf.md` (~313 tok)

## .scratch/bc-imitation/

- `smoke_bc_driver.py` — Smoke test G-003: profile schema + BCDriver dispatch + inference round-trip. (~1430 tok)
- `smoke_train.py` — Smoke test: synthesize a small HDF5 + run BC train 2 epochs + verify ONNX. (~1100 tok)

## .scratch/bc-imitation/designs/

- `impact_20260507_bc-imitation.md` — Impact Analysis — BC Imitation Auto-Play (~1769 tok)

## .scratch/ui/

- `err.txt` (~142 tok)
- `out.txt` (~0 tok)
- `requirements.md` — Requirements: unicap PyQt UI 包装器（操作员控制台） (~2219 tok)
- `smoke_full.py` — Full smoke test — exercise major code paths without a real game. (~1447 tok)
- `smoke_runner.py` — Smoke test: SubprocessRunner against main.py --version. (~283 tok)
- `smoke_window.py` — Headless test: import + create MainWindow + read tab labels + close. (~466 tok)
- `test_basic_subprocess.py` — Pure subprocess test (no Qt) — confirm Popen + line buffering works. (~177 tok)
- `test1.py` (~8 tok)
- `test2.py` (~52 tok)
- `test3.py` — URL configuration (~142 tok)

## .understand-anything/

- `.understandignore` — .understandignore — patterns for files/dirs to exclude from analysis (~290 tok)
- `fingerprints.json` (~5134 tok)
- `knowledge-graph.json` (~30986 tok)
- `meta.json` (~49 tok)

## .venv/

- `.gitignore` — Git ignore rules (~1 tok)
- `.lock` (~0 tok)
- `CACHEDIR.TAG` (~12 tok)
- `pyvenv.cfg` (~52 tok)

## .venv/Lib/site-packages/

- `_virtualenv.pth` (~5 tok)
- `_virtualenv.py` — Patches that are applied at runtime to the virtual environment. (~1241 tok)
- `distutils-precedence.pth` (~41 tok)
- `isympy.py` — main (~3206 tok)
- `typing_extensions.py` — _Sentinel: final, done, done, disjoint_base + 1 more (~45837 tok)

## .venv/Lib/site-packages/_distutils_hack/

- `__init__.py` — don't import any costly modules (~1930 tok)
- `override.py` (~13 tok)

## .venv/Lib/site-packages/_yaml/

- `__init__.py` — This is a stub package designed to roughly emulate the _yaml (~401 tok)

## .venv/Lib/site-packages/colorama-0.4.6.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` — multiple: all (~4574 tok)
- `RECORD` (~413 tok)
- `REQUESTED` (~0 tok)
- `WHEEL` (~28 tok)

## .venv/Lib/site-packages/colorama-0.4.6.dist-info/licenses/

- `LICENSE.txt` (~373 tok)

## .venv/Lib/site-packages/colorama/

- `__init__.py` (~76 tok)
- `ansi.py` — AnsiCodes: code_to_chars, set_title, clear_screen, clear_line + 5 more (~721 tok)
- `ansitowin32.py` — StreamWrapper: write, isatty, closed, should_wrap + 10 more (~3180 tok)
- `initialise.py` — reset_all, init, deinit, just_fix_windows_console + 3 more (~950 tok)
- `win32.py` — from winbase.h (~1766 tok)
- `winterm.py` — WinColor: get_osfhandle, get_attrs, set_attrs, reset_all + 11 more (~2039 tok)

## .venv/Lib/site-packages/colorama/tests/

- `__init__.py` (~22 tok)
- `ansi_test.py` — Test file (~812 tok)
- `ansitowin32_test.py` — Tests: closed_shouldnt_raise_on_closed_stream, closed_shouldnt_raise_on_detached_stream, reset_all_shouldnt_raise_on_closed_orig_stdout, wrap_shoul... (~3051 tok)
- `initialise_test.py` — Test file (~1926 tok)
- `isatty_test.py` — Tests: TTY, nonTTY, withPycharm, withPycharmTTYOverride + 3 more (~534 tok)
- `utils.py` — StreamTTY: isatty, isatty, osname, replace_by + 2 more (~309 tok)
- `winterm_test.py` — Test file (~1060 tok)

## .venv/Lib/site-packages/cv2/

- `__init__.py` — URL configuration (~1941 tok)
- `__init__.pyi` (~85743 tok)
- `config-3.py` — URL configuration (~214 tok)
- `config.py` (~36 tok)
- `LICENSE-3RD-PARTY.txt` — Declares name (~45347 tok)
- `LICENSE.txt` (~273 tok)
- `load_config_py2.py` — flake8: noqa (~45 tok)
- `load_config_py3.py` — flake8: noqa (~73 tok)
- `py.typed` (~0 tok)
- `version.py` (~28 tok)

## .venv/Lib/site-packages/cv2/Error/

- `__init__.pyi` (~1119 tok)

## .venv/Lib/site-packages/cv2/aruco/

- `__init__.pyi` — Declares Board (~4343 tok)

## .venv/Lib/site-packages/cv2/barcode/

- `__init__.pyi` — Declares BarcodeDetector (~408 tok)

## .venv/Lib/site-packages/cv2/cuda/

- `__init__.pyi` — Declares GpuMat (~4459 tok)

## .venv/Lib/site-packages/cv2/data/

- `__init__.py` (~21 tok)
- `haarcascade_eye_tree_eyeglasses.xml` (~171904 tok)
- `haarcascade_eye.xml` (~97545 tok)
- `haarcascade_frontalcatface_extended.xml` (~109405 tok)
- `haarcascade_frontalcatface.xml` (~117539 tok)
- `haarcascade_frontalface_alt.xml` (~193346 tok)
- `haarcascade_frontalface_alt2.xml` (~154462 tok)
- `haarcascade_frontalface_default.xml` (~265751 tok)
- `haarcascade_fullbody.xml` (~136237 tok)
- `haarcascade_lefteye_2splits.xml` (~55820 tok)
- `haarcascade_license_plate_rus_16stages.xml` (~13650 tok)
- `haarcascade_lowerbody.xml` (~112950 tok)
- `haarcascade_profileface.xml` (~236719 tok)
- `haarcascade_righteye_2splits.xml` (~56049 tok)
- `haarcascade_russian_plate_number.xml` (~21567 tok)
- `haarcascade_smile.xml` (~53859 tok)
- `haarcascade_upperbody.xml` (~224520 tok)

## .venv/Lib/site-packages/cv2/detail/

- `__init__.pyi` — Declares Blender (~6127 tok)

## .venv/Lib/site-packages/cv2/dnn/

- `__init__.pyi` — Declares DictValue (~6586 tok)

## .venv/Lib/site-packages/cv2/fisheye/

- `__init__.pyi` (~2676 tok)

## .venv/Lib/site-packages/cv2/flann/

- `__init__.pyi` — Declares Index (~750 tok)

## .venv/Lib/site-packages/cv2/gapi/

- `__init__.py` — GOpaque: register, parameterized, networks, compile_args + 9 more (~3035 tok)
- `__init__.pyi` — Declares GNetParam (~3996 tok)

## .venv/Lib/site-packages/cv2/gapi/core/

- `__init__.pyi` (~40 tok)

## .venv/Lib/site-packages/cv2/gapi/core/cpu/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/core/fluid/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/core/ocl/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/ie/

- `__init__.pyi` — Declares PyParams (~312 tok)

## .venv/Lib/site-packages/cv2/gapi/ie/detail/

- `__init__.pyi` (~75 tok)

## .venv/Lib/site-packages/cv2/gapi/imgproc/

- `__init__.pyi` (~21 tok)

## .venv/Lib/site-packages/cv2/gapi/imgproc/fluid/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/oak/

- `__init__.pyi` (~473 tok)

## .venv/Lib/site-packages/cv2/gapi/onnx/

- `__init__.pyi` — Declares PyParams (~414 tok)

## .venv/Lib/site-packages/cv2/gapi/onnx/ep/

- `__init__.pyi` — Declares CoreML (~379 tok)

## .venv/Lib/site-packages/cv2/gapi/ot/

- `__init__.pyi` — Declares ObjectTrackerParams (~201 tok)

## .venv/Lib/site-packages/cv2/gapi/ot/cpu/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/ov/

- `__init__.pyi` — Declares PyParams (~726 tok)

## .venv/Lib/site-packages/cv2/gapi/own/

- `__init__.pyi` (~20 tok)

## .venv/Lib/site-packages/cv2/gapi/own/detail/

- `__init__.pyi` (~40 tok)

## .venv/Lib/site-packages/cv2/gapi/render/

- `__init__.pyi` (~19 tok)

## .venv/Lib/site-packages/cv2/gapi/render/ocv/

- `__init__.pyi` (~28 tok)

## .venv/Lib/site-packages/cv2/gapi/streaming/

- `__init__.pyi` — Declares queue_capacity (~228 tok)

## .venv/Lib/site-packages/cv2/gapi/video/

- `__init__.pyi` (~43 tok)

## .venv/Lib/site-packages/cv2/gapi/wip/

- `__init__.pyi` — Declares GOutputs (~317 tok)

## .venv/Lib/site-packages/cv2/gapi/wip/draw/

- `__init__.pyi` — Declares Text (~875 tok)

## .venv/Lib/site-packages/cv2/gapi/wip/gst/

- `__init__.pyi` — Declares GStreamerPipeline (~130 tok)

## .venv/Lib/site-packages/cv2/gapi/wip/onevpl/

- `__init__.pyi` (~111 tok)

## .venv/Lib/site-packages/cv2/instr/

- `__init__.pyi` (~123 tok)

## .venv/Lib/site-packages/cv2/ipp/

- `__init__.pyi` (~64 tok)

## .venv/Lib/site-packages/cv2/mat_wrapper/

- `__init__.py` — Declares Mat (~333 tok)

## .venv/Lib/site-packages/cv2/misc/

- `__init__.py` (~11 tok)
- `version.py` — get_ocv_version (~28 tok)

## .venv/Lib/site-packages/cv2/ml/

- `__init__.pyi` — Declares ParamGrid (~6320 tok)

## .venv/Lib/site-packages/cv2/ocl/

- `__init__.pyi` — Declares Device (~1542 tok)

## .venv/Lib/site-packages/cv2/ogl/

- `__init__.pyi` (~407 tok)

## .venv/Lib/site-packages/cv2/parallel/

- `__init__.pyi` (~36 tok)

## .venv/Lib/site-packages/cv2/samples/

- `__init__.pyi` (~90 tok)

## .venv/Lib/site-packages/cv2/segmentation/

- `__init__.pyi` — Declares IntelligentScissorsMB (~475 tok)

## .venv/Lib/site-packages/cv2/typing/

- `__init__.py` — Declares providing (~1585 tok)

## .venv/Lib/site-packages/cv2/utils/

- `__init__.py` — testOverwriteNativeMethod (~99 tok)
- `__init__.pyi` — Declares ClassWithKeywordProperties (~999 tok)

## .venv/Lib/site-packages/cv2/utils/fs/

- `__init__.pyi` (~25 tok)

## .venv/Lib/site-packages/cv2/utils/logging/

- `__init__.pyi` (~141 tok)

## .venv/Lib/site-packages/cv2/utils/nested/

- `__init__.pyi` — Declares ExportClassName (~162 tok)

## .venv/Lib/site-packages/cv2/videoio_registry/

- `__init__.pyi` (~265 tok)

## .venv/Lib/site-packages/filelock-3.29.0.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` (~527 tok)
- `RECORD` (~442 tok)
- `REQUESTED` (~0 tok)
- `WHEEL` (~24 tok)

## .venv/Lib/site-packages/filelock-3.29.0.dist-info/licenses/

- `LICENSE` — Project license (~290 tok)

## .venv/Lib/site-packages/filelock/

- `__init__.py` (~747 tok)
- `_api.py` — URL configuration (~6099 tok)
- `_async_read_write.py` — Async wrapper around :class:`ReadWriteLock` for use with ``asyncio``. (~2217 tok)
- `_error.py` — Timeout: lock_file (~226 tok)
- `_read_write.py` — URL configuration (~4378 tok)
- `_soft.py` — SoftFileLock: pid, is_lock_held_by_us, break_lock (~2238 tok)
- `_unix.py` — : a flag to indicate if the fcntl API is available (~1308 tok)
- `_util.py` — raise_on_not_writable_file, ensure_directory_exists (~491 tok)
- `_windows.py` — Declares WindowsFileLock (~1127 tok)
- `asyncio.py` — An asyncio-based implementation of the file lock. (~4157 tok)
- `py.typed` (~0 tok)
- `version.py` — file generated by vcs-versioning (~150 tok)

## .venv/Lib/site-packages/filelock/_soft_rw/

- `__init__.py` — Cross-process and cross-host reader/writer lock on :class:`~filelock.SoftFileLock` primitives. (~106 tok)
- `_async.py` — Async wrapper around :class:`SoftReadWriteLock` for use with ``asyncio``. (~2487 tok)
- `_sync.py` — Cross-process and cross-host reader/writer lock built on :class:`SoftFileLock` primitives. (~9975 tok)

## .venv/Lib/site-packages/flatbuffers-25.12.19.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` (~268 tok)
- `RECORD` (~349 tok)
- `REQUESTED` (~0 tok)
- `top_level.txt` (~3 tok)
- `WHEEL` (~30 tok)

## .venv/Lib/site-packages/flatbuffers/

- `__init__.py` — you may not use this file except in compliance with the License. (~215 tok)
- `_version.py` — you may not use this file except in compliance with the License. (~199 tok)
- `builder.py` — you may not use this file except in compliance with the License. (~7020 tok)
- `compat.py` — A tiny version of `six` to help with backwards compability. (~678 tok)
- `encode.py` — you may not use this file except in compliance with the License. (~443 tok)
- `flexbuffers.py` — Implementation of FlexBuffers binary format. (~12702 tok)
- `number_types.py` — you may not use this file except in compliance with the License. (~1075 tok)
- `packer.py` — Provide pre-compiled struct packers for encoding and decoding. (~333 tok)
- `table.py` — you may not use this file except in compliance with the License. (~1377 tok)
- `util.py` — you may not use this file except in compliance with the License. (~460 tok)

## .venv/Lib/site-packages/fsspec-2026.4.0.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` (~2807 tok)
- `RECORD` (~1395 tok)
- `REQUESTED` (~0 tok)
- `WHEEL` (~24 tok)

## .venv/Lib/site-packages/fsspec-2026.4.0.dist-info/licenses/

- `LICENSE` — Project license (~404 tok)

## .venv/Lib/site-packages/fsspec/

- `__init__.py` — process_entries (~587 tok)
- `_version.py` — file generated by vcs-versioning (~151 tok)
- `archive.py` — AbstractArchiveFileSystem: ukey, info, ls (~689 tok)
- `asyn.py` — URL configuration (~10739 tok)
- `caching.py` — BaseCache: block (~9722 tok)
- `callbacks.py` — Callback: close, branched, branch_coro, func + 14 more (~2632 tok)
- `compression.py` — Helper functions for a standard streaming compression API (~1467 tok)
- `config.py` — Augments: set_conf_env, set_conf_files, apply_config (~1211 tok)
- `conftest.py` — InstanceCacheInspector: m, clear, gather_counts, instance_caches + 2 more (~985 tok)
- `core.py` — for backwards compat, we export cache things from here too (~6907 tok)
- `dircache.py` — DirCache: clear (~777 tok)
- `exceptions.py` — Declares BlocksizeMismatchError (~95 tok)
- `fuse.py` — FUSEr: getattr, readdir, mkdir, rmdir + 11 more (~2908 tok)
- `generic.py` — GenericFileSystem: set_generic_fs, rsync, rsync, copy_file_op (~3852 tok)
- `gui.py` — URL configuration (~3998 tok)
- `json.py` — from: default, make_serializable, try_resolve_path_cls, try_resolve_fs_cls + 2 more (~1077 tok)
- `mapping.py` — FSMap: dirfs, clear, getitems, setitems + 4 more (~2384 tok)
- `parquet.py` — Parquet-Specific Utilities for fsspec (~5859 tok)
- `registry.py` — to: register_implementation, get_filesystem_class, filesystem, available_protocols (~3527 tok)
- `spec.py` — URL configuration (~22215 tok)
- `transaction.py` — Transaction: start, complete, commit, discard + 2 more (~686 tok)
- `utils.py` — URL configuration (~6750 tok)

## .venv/Lib/site-packages/fsspec/implementations/

- `__init__.py` (~0 tok)
- `arrow.py` — ArrowFSWrapper: wrap_exceptions, wrapper, protocol, fsid + 14 more (~2540 tok)
- `asyn_wrapper.py` — AsyncFileSystemWrapper: async_wrapper, wrapper, fsid, wrap_class (~1068 tok)
- `cache_mapper.py` — AbstractCacheMapper: create_cache_mapper (~692 tok)
- `cache_metadata.py` — CacheMetadata: check_file, clear_expired, load, on_close_cached_file + 3 more (~2430 tok)
- `cached.py` — WriteCachedTransaction: complete, cache_size, load_cache, save_cache + 3 more (~10393 tok)
- `chained.py` — Declares ChainedFileSystem (~195 tok)
- `dask.py` — DaskWorkerFileSystem: mkdir, rm, copy, mv + 2 more (~1276 tok)
- `data.py` — DataFileSystem: cat_file, info, encode (~465 tok)
- `dbfs.py` — DatabricksException: ls, makedirs, mkdir, rm + 1 more (~4634 tok)
- `dirfs.py` — View: delete, put, get (~3607 tok)
- `ftp.py` — URL configuration (~3782 tok)
- `gist.py` — URL configuration (~2437 tok)
- `git.py` — GitFileSystem: ls, info, ukey (~1066 tok)
- `github.py` — URL configuration (~3330 tok)
- `http_sync.py` — This file is largely copied from http.py (~8667 tok)
- `http.py` — HTTPFileSystem: get_client, fsid, encode_url, close_session + 2 more (~8827 tok)
- `jupyter.py` — JupyterFileSystem: ls, cat_file, pipe_file, mkdir + 1 more (~1144 tok)
- `libarchive.py` — LibArchiveFileSystem: custom_reader, read_func, seek_func (~2028 tok)
- `local.py` — URL configuration (~4904 tok)
- `memory.py` — URL configuration (~3002 tok)
- `reference.py` — ReferenceNotReachable: ravel_multi_index, np, pd, setup + 4 more (~14057 tok)
- `sftp.py` — URL configuration (~1701 tok)
- `smb.py` — URL configuration (~4354 tok)
- `tar.py` — TarFileSystem: close (~1272 tok)
- `webhdfs.py` — https://hadoop.apache.org/docs/r1.0.4/webhdfs.html (~5026 tok)
- `zip.py` — ZipFileSystem: close, pipe_file, find, to_parts (~1790 tok)

## .venv/Lib/site-packages/fsspec/tests/abstract/

- `__init__.py` — URL configuration (~2852 tok)
- `common.py` (~1421 tok)
- `copy.py` — AbstractCopyTests: test_copy_file_to_existing_directory, test_copy_file_to_new_directory, test_copy_file_to_file_in_existing_directory, test_copy_f... (~5705 tok)
- `get.py` — AbstractGetTests: test_get_file_to_existing_directory, test_get_file_to_new_directory, test_get_file_to_file_in_existing_directory, test_get_file_t... (~5930 tok)
- `mv.py` — test_move_raises_error_with_tmpdir, test_move_raises_error_with_tmpdir_permission (~567 tok)
- `open.py` — AbstractOpenTests: test_open_exclusive (~94 tok)
- `pipe.py` — AbstractPipeTests: test_pipe_exclusive (~115 tok)
- `put.py` — AbstractPutTests: test_put_file_to_existing_directory, test_put_file_to_new_directory, test_put_file_to_file_in_existing_directory, test_put_file_t... (~6058 tok)

## .venv/Lib/site-packages/functorch/

- `__init__.py` — All rights reserved. (~308 tok)

## .venv/Lib/site-packages/functorch/_src/

- `__init__.py` (~0 tok)

## .venv/Lib/site-packages/functorch/_src/aot_autograd/

- `__init__.py` — This file has moved to under torch/_functorch. It is not public API. (~86 tok)

## .venv/Lib/site-packages/functorch/_src/eager_transforms/

- `__init__.py` — This file has moved to under torch/_functorch. It is not public API. (~86 tok)

## .venv/Lib/site-packages/functorch/_src/make_functional/

- `__init__.py` — This file has moved to under torch/_functorch. It is not public API. (~69 tok)

## .venv/Lib/site-packages/functorch/_src/vmap/

- `__init__.py` — This file has moved to under torch/_functorch. It is not public API. (~138 tok)

## .venv/Lib/site-packages/functorch/compile/

- `__init__.py` (~225 tok)

## .venv/Lib/site-packages/functorch/dim/

- `__init__.py` — DimList: handle_from_tensor, dims, genobject, bind_len + 5 more (~15834 tok)
- `_dim_entry.py` — DimEntry: is_positional, is_none, position, dim + 1 more (~1152 tok)
- `_enable_all_layers.py` — EnableAllLayers: from_batched, inplace_update_layers (~1533 tok)
- `_getsetitem.py` — class: has_dims, slice_to_tuple, extractIndices, getitem + 5 more (~5610 tok)
- `_order.py` — dimensions: order, append_dim (~2070 tok)
- `_py_inst_decoder.py` — _PyInstDecoder: next, opcode, oparg, name (~622 tok)
- `_tensor_info.py` — from: ndim, create (~624 tok)
- `_wrap.py` — WrappedOperator: handle_from_tensor, function, wrapped_func, patched_dim_method + 2 more (~2481 tok)
- `magic_trace.py` — All rights reserved. (~456 tok)
- `op_properties.py` — All rights reserved. (~2000 tok)
- `wrap_type.py` — All rights reserved. (~618 tok)

## .venv/Lib/site-packages/functorch/einops/

- `__init__.py` (~18 tok)
- `_parsing.py` — Adapted from https://github.com/arogozhnikov/einops/blob/36c7bb16e57d6e57f8f3050f9e07abdf3f00469f/einops/parsing.py. (~3605 tok)
- `rearrange.py` — dimensions: composition_to_dims, rearrange (~2393 tok)

## .venv/Lib/site-packages/functorch/experimental/

- `__init__.py` — PyTorch forward-mode is not mature yet (~80 tok)
- `control_flow.py` (~43 tok)
- `ops.py` (~17 tok)

## .venv/Lib/site-packages/google/_upb/

- `_message.pyd` (~192161 tok)

## .venv/Lib/site-packages/google/protobuf/

- `__init__.py` — Protocol Buffers - Google's data interchange format (~99 tok)
- `any_pb2.py` — Generated protocol buffer code. (~493 tok)
- `any.py` — Contains the Any helper APIs. (~377 tok)
- `api_pb2.py` — Generated protocol buffer code. (~1029 tok)
- `descriptor_database.py` — Provides a container for DescriptorProtos. (~1696 tok)
- `descriptor_pb2.py` — Generated protocol buffer code. (~105494 tok)
- `descriptor_pool.py` — Provides DescriptorPool to use as a container for proto2 descriptors. (~13962 tok)
- `descriptor.py` — Descriptors essentially contain exactly the information found in a .proto (~15183 tok)
- `duration_pb2.py` — Generated protocol buffer code. (~516 tok)
- `duration.py` — Contains the Duration helper APIs. (~764 tok)
- `empty_pb2.py` — Generated protocol buffer code. (~477 tok)
- `field_mask_pb2.py` — Generated protocol buffer code. (~505 tok)
- `json_format.py` — Contains routines for printing protocol messages in JSON format. (~10658 tok)
- `message_factory.py` — Provides a factory class for generating dynamic messages. (~1888 tok)
- `message.py` — Protocol Buffers - Google's data interchange format (~4262 tok)
- `proto_builder.py` — Dynamic Protobuf class creator. (~1201 tok)
- `proto_json.py` — Contains the Nextgen Pythonic Protobuf JSON APIs. (~842 tok)
- `proto_text.py` — Contains the Nextgen Pythonic Protobuf Text Format APIs. (~1328 tok)
- `proto.py` — Contains the Nextgen Pythonic protobuf APIs. (~1254 tok)
- `reflection.py` — Protocol Buffers - Google's data interchange format (~355 tok)
- `runtime_version.py` — Protobuf Runtime versions and validators. (~867 tok)
- `service_reflection.py` — Contains metaclasses used to create protocol service and service stub (~2874 tok)
- `source_context_pb2.py` — Generated protocol buffer code. (~512 tok)
- `struct_pb2.py` — Generated protocol buffer code. (~875 tok)
- `symbol_database.py` — A database of Python protocol buffer generated symbols. (~1644 tok)
- `text_encoding.py` — Encoding related utilities. (~1035 tok)
- `text_format.py` — Contains routines for printing protocol messages in text format. (~17964 tok)
- `timestamp_pb2.py` — Generated protocol buffer code. (~519 tok)
- `timestamp.py` — Contains the Timestamp helper APIs. (~896 tok)
- `type_pb2.py` — Generated protocol buffer code. (~1554 tok)
- `unknown_fields.py` — Contains Unknown Fields APIs. (~876 tok)
- `wrappers_pb2.py` — Generated protocol buffer code. (~868 tok)

## .venv/Lib/site-packages/google/protobuf/compiler/

- `__init__.py` (~0 tok)
- `plugin_pb2.py` — Generated protocol buffer code. (~1085 tok)

## .venv/Lib/site-packages/google/protobuf/internal/

- `__init__.py` — Protocol Buffers - Google's data interchange format (~78 tok)
- `api_implementation.py` — Determine which implementation of the protobuf API is used in this process. (~1334 tok)
- `builder.py` — Builds descriptors, message classes and services for generated _pb2.py. (~1189 tok)
- `containers.py` — Contains container classes to represent different protocol buffer types. (~6701 tok)
- `decoder.py` — Code for decoding protocol buffer primitives. (~10860 tok)
- `encoder.py` — Code for encoding protocol message primitives. (~7800 tok)
- `enum_type_wrapper.py` — A simple wrapper around enum types to expose utility functions. (~1071 tok)
- `extension_dict.py` — Contains _ExtensionDict class to represent extensions. (~2041 tok)
- `field_mask.py` — Contains FieldMask class. (~2983 tok)
- `message_listener.py` — Defines a listener interface for observing certain (~574 tok)
- `python_edition_defaults.py` (~155 tok)
- `python_message.py` — Protocol Buffers - Google's data interchange format (~16582 tok)
- `testing_refleaks.py` — A subclass of unittest.TestCase which checks for reference leaks. (~1285 tok)
- `type_checkers.py` — Provides type checking routines. (~4739 tok)
- `well_known_types.py` — Contains well known classes. (~6668 tok)
- `wire_format.py` — Constants and static functions to support protocol buffer wire format. (~2025 tok)

## .venv/Lib/site-packages/google/protobuf/pyext/

- `__init__.py` (~0 tok)
- `cpp_message.py` — Protocol message implementation hooks for C++ implementation. (~490 tok)

## .venv/Lib/site-packages/google/protobuf/testdata/

- `__init__.py` (~0 tok)

## .venv/Lib/site-packages/google/protobuf/util/

- `__init__.py` (~0 tok)

## .venv/Lib/site-packages/h5py-3.16.0.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` — Declares to (~819 tok)
- `RECORD` (~2389 tok)
- `REQUESTED` (~0 tok)
- `top_level.txt` (~2 tok)
- `WHEEL` (~27 tok)

## .venv/Lib/site-packages/h5py-3.16.0.dist-info/licenses/

- `LICENSE` — Project license (~414 tok)

## .venv/Lib/site-packages/h5py-3.16.0.dist-info/licenses/licenses/

- `hdf5.txt` (~959 tok)
- `license.txt` (~444 tok)
- `pytables.txt` (~419 tok)
- `python.txt` (~637 tok)
- `stdint.txt` (~355 tok)

## .venv/Lib/site-packages/h5py-3.16.0.dist-info/licenses/lzf/

- `LICENSE.txt` (~398 tok)

## .venv/Lib/site-packages/h5py/

- `__init__.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1092 tok)
- `_conv.cp313-win_amd64.pyd` (~45522 tok)
- `_errors.cp313-win_amd64.pyd` (~12602 tok)
- `_npystrings.cp313-win_amd64.pyd` (~12875 tok)
- `_objects.cp313-win_amd64.pyd` (~32780 tok)
- `_proxy.cp313-win_amd64.pyd` (~11924 tok)
- `_selector.cp313-win_amd64.pyd` (~34154 tok)
- `defs.cp313-win_amd64.pyd` (~39719 tok)
- `h5.cp313-win_amd64.pyd` (~21960 tok)
- `h5a.cp313-win_amd64.pyd` (~29919 tok)
- `h5ac.cp313-win_amd64.pyd` (~14235 tok)
- `h5d.cp313-win_amd64.pyd` (~59207 tok)
- `h5ds.cp313-win_amd64.pyd` (~18827 tok)
- `h5f.cp313-win_amd64.pyd` (~32673 tok)
- `h5fd.cp313-win_amd64.pyd` (~35646 tok)
- `h5g.cp313-win_amd64.pyd` (~35404 tok)
- `h5i.cp313-win_amd64.pyd` (~15312 tok)
- `h5l.cp313-win_amd64.pyd` (~24399 tok)
- `h5o.cp313-win_amd64.pyd` (~29687 tok)
- `h5p.cp313-win_amd64.pyd` (~81559 tok)
- `h5pl.cp313-win_amd64.pyd` (~11921 tok)
- `h5py_warnings.py` — This file is part of h5py, a Python interface to the HDF5 library. (~156 tok)
- `h5r.cp313-win_amd64.pyd` (~16679 tok)
- `h5s.cp313-win_amd64.pyd` (~30076 tok)
- `h5t.cp313-win_amd64.pyd` (~89273 tok)
- `h5z.cp313-win_amd64.pyd` (~13275 tok)
- `ipy_completer.py` — This file is part of h5py, a low-level Python interface to the HDF5 library. (~1112 tok)
- `utils.cp313-win_amd64.pyd` (~14648 tok)
- `version.py` — This file is part of h5py, a Python interface to the HDF5 library. (~565 tok)

## .venv/Lib/site-packages/h5py/_hl/

- `__init__.py` — This file is part of h5py, a Python interface to the HDF5 library. (~135 tok)
- `attrs.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2996 tok)
- `base.py` — This file is part of h5py, a Python interface to the HDF5 library. (~4639 tok)
- `compat.py` — URL configuration (~449 tok)
- `dataset.py` — This file is part of h5py, a Python interface to the HDF5 library. (~13298 tok)
- `datatype.py` — This file is part of h5py, a Python interface to the HDF5 library. (~458 tok)
- `dims.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1512 tok)
- `files.py` — This file is part of h5py, a Python interface to the HDF5 library. (~7374 tok)
- `filters.py` — This file is part of h5py, a Python interface to the HDF5 library. (~4291 tok)
- `group.py` — This file is part of h5py, a Python interface to the HDF5 library. (~10063 tok)
- `selections.py` — This file is part of h5py, a Python interface to the HDF5 library. (~4322 tok)
- `selections2.py` — This file is part of h5py, a Python interface to the HDF5 library. (~808 tok)
- `vds.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2777 tok)

## .venv/Lib/site-packages/h5py/tests/

- `__init__.py` — This file is part of h5py, a Python interface to the HDF5 library. (~182 tok)
- `common.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2730 tok)
- `conftest.py` — writable_file, pytest_addoption, pytest_collection_modifyitems (~162 tok)
- `test_attribute_create.py` — This file is part of h5py, a Python interface to the HDF5 library. (~938 tok)
- `test_attrs_data.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2993 tok)
- `test_attrs.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2848 tok)
- `test_base.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1178 tok)
- `test_big_endian_file.py` — URL patterns: 1 routes (~434 tok)
- `test_completions.py` — Tests: root_group_completions, subgroup_completions, attrs_completions (~558 tok)
- `test_dataset_getitem.py` — This file is part of h5py, a Python interface to the HDF5 library. (~6198 tok)
- `test_dataset_swmr.py` — Tests: initial_swmr_mode_on, read_data, refresh, force_swmr_mode_on_raises + 6 more (~1195 tok)
- `test_dataset.py` — This file is part of h5py, a Python interface to the HDF5 library. (~26031 tok)
- `test_datatype.py` — This file is part of h5py, a Python interface to the HDF5 library. (~324 tok)
- `test_dimension_scales.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2472 tok)
- `test_dims_dimensionproxy.py` — This file is part of h5py, a Python interface to the HDF5 library. (~176 tok)
- `test_dtype.py` — Tests: compound, compound_vlen_bool, compound_vlen_enum, vlen_enum + 9 more (~5909 tok)
- `test_errors.py` — This file is part of h5py, a Python interface to the HDF5 library. (~703 tok)
- `test_file_alignment.py` — Tests: no_alignment_set, alignment_set_above_threshold, alignment_set_below_threshold (~1313 tok)
- `test_file_image.py` — Tests: load_from_image, open_from_image, in_memory (~590 tok)
- `test_file.py` — This file is part of h5py, a Python interface to the HDF5 library. (~10384 tok)
- `test_file2.py` — This file is part of h5py, a Python interface to the HDF5 library. (~3285 tok)
- `test_filters.py` — This file is part of h5py, a Python interface to the HDF5 library. (~948 tok)
- `test_group.py` — -*- coding: utf-8 -*- (~14351 tok)
- `test_h5.py` — This file is part of h5py, a Python interface to the HDF5 library. (~361 tok)
- `test_h5d_direct_chunk.py` — Tests: write_direct_chunk, read_compressed_offsets, read_uncompressed_offsets, read_write_chunk + 5 more (~2285 tok)
- `test_h5f.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1154 tok)
- `test_h5o.py` — Tests: visit (~155 tok)
- `test_h5p.py` — This file is part of h5py, a Python interface to the HDF5 library. (~2380 tok)
- `test_h5pl.py` — This file is part of h5py, a Python interface to the HDF5 library. (~548 tok)
- `test_h5s.py` — Tests: same_shape, select_copy, combine_select, modify_select (~633 tok)
- `test_h5t.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1938 tok)
- `test_h5z.py` — Tests: register_filter, unregister_filter (~588 tok)
- `test_native_complex.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1667 tok)
- `test_npystrings.py` — Tests: create_with_dtype_T, fromdata, fixed_to_variable_width, fixed_to_variable_width_too_short + 7 more (~1724 tok)
- `test_objects.py` — This file is part of h5py, a Python interface to the HDF5 library. (~896 tok)
- `test_ros3.py` — This file is part of h5py, a Python interface to the HDF5 library. (~998 tok)
- `test_selections.py` — This file is part of h5py, a Python interface to the HDF5 library. (~1438 tok)
- `test_slicing.py` — This file is part of h5py, a Python interface to the HDF5 library. (~4166 tok)

## .venv/Lib/site-packages/h5py/tests/data_files/

- `__init__.py` — URL configuration (~58 tok)
- `compound-dtype-complex.h5` (~3612 tok)
- `vlen_string_dset_utc.h5` (~45308 tok)
- `vlen_string_dset.h5` (~1682 tok)
- `vlen_string_s390x.h5` (~2402 tok)

## .venv/Lib/site-packages/h5py/tests/test_vds/

- `__init__.py` (~31 tok)
- `test_highlevel_vds.py` — Tests: eiger_high_level, excalibur_high_level, percival_high_level, percival_source_from_dataset + 4 more (~5239 tok)
- `test_lowlevel_vds.py` — Tests: eiger_low_level, excalibur_low_level, percival_low_level, virtual_prefix (~3495 tok)
- `test_virtual_source.py` — Tests: full_slice, full_slice_inverted, subsampled_slice_inverted, integer_indexed + 22 more (~1778 tok)

## .venv/Lib/site-packages/jinja2-3.1.6.dist-info/

- `entry_points.txt` (~15 tok)
- `INSTALLER` (~1 tok)
- `METADATA` (~766 tok)
- `RECORD` (~670 tok)
- `REQUESTED` (~0 tok)
- `WHEEL` (~22 tok)

## .venv/Lib/site-packages/jinja2-3.1.6.dist-info/licenses/

- `LICENSE.txt` (~369 tok)

## .venv/Lib/site-packages/jinja2/

- `__init__.py` — Jinja is a template engine written in pure Python. It provides a (~551 tok)
- `_identifier.py` (~277 tok)
- `async_utils.py` — _IteratorToAsyncIterator: async_variant, decorator, is_async, is_async + 4 more (~810 tok)
- `bccache.py` — The optional bytecode cache system. This is useful if you have very (~4018 tok)
- `compiler.py` — Compiles nodes from the parser into Python code. (~21181 tok)
- `constants.py` — : list of lorem ipsum words used by the lipsum() helper function (~410 tok)
- `debug.py` — rewrite_traceback_stack, fake_traceback, get_template_locals (~1800 tok)
- `defaults.py` (~362 tok)
- `environment.py` — Classes for managing templates and their runtime and compile time (~17576 tok)
- `exceptions.py` — TemplateError: message (~1449 tok)
- `ext.py` — Extension API for adding custom tags and behavior. (~9108 tok)
- `filters.py` — Built-in template filters used with the ``|`` operator. (~15775 tok)
- `idtracking.py` — Symbols: find_symbols, symbols_for_node, analyze_node, find_load + 31 more (~3016 tok)
- `lexer.py` — Implements a Jinja / Python combination lexer. The ``Lexer`` class (~8511 tok)
- `loaders.py` — API and implementations for loading templates from different data (~6873 tok)
- `meta.py` — Functions that expose information about templates that might be (~1257 tok)
- `nativetypes.py` — NativeCodeGenerator: native_concat, render, render_async (~1203 tok)
- `nodes.py` — AST nodes generated by the parser for the compiler. Also provides (~9880 tok)
- `optimizer.py` — The optimizer tries to constant fold expressions and modify the AST (~472 tok)
- `parser.py` — Parse tokens from the lexer into nodes for the compiler. (~11538 tok)
- `py.typed` (~0 tok)
- `runtime.py` — The runtime functions and state used by compiled templates. (~9786 tok)
- `sandbox.py` — A sandbox layer that ensures unsafe operations cannot be performed. (~4289 tok)
- `tests.py` — Built-in template tests used with the ``is`` operator. (~1694 tok)
- `utils.py` — _MissingType: pass_context, pass_eval_context, pass_environment, from_obj + 13 more (~6894 tok)
- `visitor.py` — API for traversing the AST nodes. Implemented by the compiler and (~1017 tok)

## .venv/Lib/site-packages/markupsafe-3.0.3.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` (~738 tok)
- `RECORD` (~289 tok)
- `REQUESTED` (~0 tok)
- `top_level.txt` (~3 tok)
- `WHEEL` (~27 tok)

## .venv/Lib/site-packages/markupsafe-3.0.3.dist-info/licenses/

- `LICENSE.txt` (~376 tok)

## .venv/Lib/site-packages/markupsafe/

- `__init__.py` — _HasHTML: escape, escape_silent, soft_str, join + 29 more (~3898 tok)
- `_native.py` (~63 tok)
- `_speedups.c` — include <Python.h> (~1294 tok)
- `_speedups.cp313-win_amd64.pyd` (~3527 tok)
- `_speedups.pyi` (~12 tok)
- `py.typed` (~0 tok)

## .venv/Lib/site-packages/ml_dtypes-0.5.4.dist-info/

- `INSTALLER` (~1 tok)
- `METADATA` — Declares extensions (~2447 tok)
- `RECORD` (~293 tok)
- `REQUESTED` (~0 tok)
- `top_level.txt` (~3 tok)
- `WHEEL` (~27 tok)

## .venv/Lib/site-packages/ml_dtypes-0.5.4.dist-info/licenses/

- `LICENSE` — Project license (~3083 tok)
- `LICENSE.eigen` (~4560 tok)

## .venv/Lib/site-packages/ml_dtypes/

- `__init__.py` — you may not use this file except in compliance with the License. (~696 tok)
- `_finfo.py` — Overload of numpy.finfo to handle dtypes defined in ml_dtypes. (~6749 tok)
- `_iinfo.py` — Overload of numpy.iinfo to handle dtypes defined in ml_dtypes. (~600 tok)
- `_ml_dtypes_ext.cp313-win_amd64.pyd` (~215671 tok)
- `py.typed` (~0 tok)

## .venv/Lib/site-packages/mpmath/

- `__init__.py` — URL configuration (~2505 tok)
- `ctx_base.py` — Context: warn, bad_domain, fneg, fadd + 15 more (~4568 tok)
- `ctx_fp.py` — FPContext: f_wrapped, bernoulli, is_special, isnan + 17 more (~1878 tok)
- `ctx_iv.py` — ivmpf: convert_mpf_, cast, real, imag + 23 more (~4918 tok)
- `ctx_mp_python.py` — from ctx_base import StandardBaseContext (~10805 tok)
- `ctx_mp.py` — MPContext: init_builtins, to_fixed, hypot, bernoulli + 4 more (~14130 tok)
- `function_docs.py` — Declares instead (~81004 tok)
- `identification.py` — IdentificationMethods: round_fixed, pslq, findpoly (~8358 tok)
- `math2.py` — f, f, f, math_log + 10 more (~5304 tok)
- `rational.py` — mpq: create_reduced (~1708 tok)
- `usertools.py` — monitor, input, output, f_monitored + 1 more (~866 tok)
- `visualization.py` — VisualizationMethods: plot, default_color_function, phase_color_function, cplot + 1 more (~3037 tok)

## .venv/Lib/site-packages/mpmath/calculus/

- `__init__.py` — XXX: hack to set methods (~47 tok)
- `approximation.py` — ----------------------------------------------------------------------------# (~2520 tok)
- `calculus.py` — CalculusMethods: defun (~32 tok)
- `differentiation.py` — difference, hsteps, diff, g + 8 more (~5779 tok)
- `extrapolation.py` — levin_class: richardson, shanks (~20945 tok)
- `inverselaplace.py` — contributed to mpmath by Kristopher L. Kuhlman, February 2017 (~10302 tok)
- `odes.py` — ODEMethods: ode_taylor, odefun, mpolyval, get_series + 1 more (~2831 tok)
- `optimization.py` — OptimizationMethods: df, df, d2f, df + 6 more (~9388 tok)
- `polynomials.py` — ----------------------------------------------------------------------------# (~2251 tok)
- `quadrature.py` — QuadratureRule: clear, calc_nodes, get_nodes, transform_nodes + 6 more (~12124 tok)

## .venv/Lib/site-packages/mpmath/functions/

- `__init__.py` — Hack to update methods (~95 tok)
- `bessel.py` — j0, j1, besselj, h + 34 more (~10840 tok)
- `elliptic.py` — eta, nome, qfrom, qbarfrom + 6 more (~12068 tok)
- `expintegrals.py` — erf, erfc, square_exp_arg, erfi + 18 more (~3327 tok)
- `factorials.py` — gammaprod, beta, binomial, rf + 9 more (~1507 tok)
- `functions.py` — SpecialFunctions: defun_wrapped, defun, defun_static, cot + 32 more (~5172 tok)
- `hypergeometric.py` — hypercomb, hyper, hyp0f1, hyp1f1 + 8 more (~14735 tok)
- `orthogonal.py` — hermite, pcfd, pcfu, pcfv + 21 more (~4600 tok)
- `qfunctions.py` — qp, terms, factors, qgamma + 3 more (~2181 tok)
- `rszeta.py` — RSCache: coef, aux_M_Fp, aux_J_needed, Rzeta_simul (~13196 tok)
- `signals.py` — squarew, trianglew, sawtoothw, unit_triangle + 1 more (~201 tok)
- `theta.py` (~10663 tok)

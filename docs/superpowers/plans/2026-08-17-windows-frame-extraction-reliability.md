# Windows Frame Extraction Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 防止 ffmpeg 无有效图片和并发临时路径冲突导致 detector 读取不存在的帧。

**Architecture:** 将有效图片验证纳入 `extract_frame()` 的三次尝试，并让 `LabelPipeline` 的全部临时图片按 `run_id` 隔离。队列消费前增加防御检查，使单图文件消失只影响该图。

**Tech Stack:** Python 3.12、subprocess、pathlib、Pillow、asyncio、pytest

---

### Task 1: 抽帧产物验证与重试

**Files:**
- Modify: `make_labels/tests/test_video_capture.py`
- Modify: `make_labels/app/video_capture.py`

- [ ] **Step 1: 编写失败测试**

测试假 ffmpeg 返回 0 但前两次不创建文件、第三次创建有效 JPEG 时 `extract_frame()` 成功且总调用三次；测试三次均无文件、明显无效图片，以及可通过 `verify()` 但不能完整解码的截断 JPEG 均抛出包含 `output frame` 的 `VideoCommandError`。

- [ ] **Step 2: 运行 RED**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_video_capture.py -q`

Expected: 新测试失败，因为当前实现返回不存在或无效的路径。

- [ ] **Step 3: 实现最小修复**

为 `extract_frame()` 增加 `retries` 和 `retry_delay_seconds` 关键字参数。每次调用 `run_video_command(..., retries=0)` 前删除旧文件，调用后依次验证 `is_file()`、`stat().st_size` 和 `Image.open(...).load()` 完整像素解码；失败时按预算重试，最终抛出 `VideoCommandError`。ffmpeg 参数增加 `-update 1`。

- [ ] **Step 4: 运行 GREEN**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_video_capture.py -q`

Expected: PASS。

### Task 2: 任务临时路径隔离与消费端防御

**Files:**
- Modify: `make_labels/tests/test_job_runtime.py`
- Modify: `make_labels/app/pipeline.py`

- [ ] **Step 1: 编写失败测试**

测试不同 `run_id` 的相同课程得到不同临时目录；测试 `label_frame()` 收到不存在路径时不调用 detector、增加过滤计数并记录“抽帧文件不存在”错误。

- [ ] **Step 2: 运行 RED**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_job_runtime.py -q`

Expected: 新测试失败，因为当前流水线没有 `run_id` 隔离或 detector 前防御检查。

- [ ] **Step 3: 实现最小修复**

`LabelPipeline.__init__` 创建 UUID `run_id`，新增 `course_tmp_dir(course_id)`，probe、正式帧、主体预览和标签预览统一使用该目录。`label_frame()` 开头检查 `frame_path.is_file()` 和非零大小，失败时记录单图错误并返回。

- [ ] **Step 4: 运行 GREEN**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_job_runtime.py -q`

Expected: PASS。

### Task 3: 完整验证与交付

**Files:**
- Modify: `make_labels/README.md`

- [ ] **Step 1: 补充 Windows 运行说明**

说明抽帧成功以有效 JPEG 为准、临时目录按任务隔离，单图抽帧失败会记录明确错误而不会进入 detector。

- [ ] **Step 2: 完整验证**

Run: `cd make_labels && conda run -n make_label python -m pytest tests -q`

Run: `cd make_labels && conda run -n make_label python -m compileall -q app scripts tests`

Run: `cd make_labels && conda run -n make_label python -m pip check`

Expected: 全部退出码为 0。

- [ ] **Step 3: 安全扫描并提交**

只暂存本计划、设计文档和明确修改文件，确认 staged diff 不包含视频签名 URL、API key、Base64、图片、`make_labels.zip` 或本地配置。使用中文提交 `fix: 提升 Windows 抽帧可靠性` 并推送 `origin main`。

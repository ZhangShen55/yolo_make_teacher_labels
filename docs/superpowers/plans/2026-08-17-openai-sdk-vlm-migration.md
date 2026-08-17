# OpenAI SDK VLM Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `make_labels` 的主服务、预检和离线图片脚本统一迁移到 OpenAI Python SDK，并使用 Ark OpenAI-compatible base URL 与指定模型完成真实图片验证。

**Architecture:** 保留 `ArkVlmClient` 作为项目内唯一 VLM 边界，内部由 `AsyncOpenAI` 调用 Responses API。预检和离线脚本复用该客户端，响应文本与可序列化原始响应由统一方法处理；教师 ImageDetect 仍保留现有 `requests` 重试链路。

**Tech Stack:** Python 3.12、OpenAI Python SDK 3.1.0、Responses API、pytest、FastAPI

---

### Task 1: 固化 SDK 客户端契约

**Files:**
- Modify: `make_labels/tests/test_vlm_labeler.py`
- Modify: `make_labels/app/vlm_labeler.py`
- Modify: `make_labels/requirements.txt`

- [ ] **Step 1: 编写失败测试**

新增测试，以注入的假 `AsyncOpenAI` 客户端验证：`base_url`、`api_key`、`timeout` 初始化参数正确；`responses.create()` 收到指定 `model` 和包含图片 data URL、文本提示词的 `input`；返回对象的 `output_text` 可被提取，`model_dump()` 可生成原始响应字典。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_vlm_labeler.py -q`

Expected: FAIL，原因是尚未使用 `AsyncOpenAI` 或尚无统一的响应序列化接口。

- [ ] **Step 3: 实现最小 SDK 客户端**

在 `ArkVlmClient` 中创建 `AsyncOpenAI(base_url=api_url, api_key=api_key, timeout=timeout_seconds)`，通过 `client.responses.create(model=self.model, input=[...])` 请求；增加统一响应文本提取和 `model_dump()` 序列化。将 `openai==3.1.0` 加入 requirements，移除该模块不再需要的 `httpx` 导入。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_vlm_labeler.py -q`

Expected: PASS。

### Task 2: 让预检复用统一客户端

**Files:**
- Modify: `make_labels/tests/test_api.py`
- Modify: `make_labels/app/preflight.py`

- [ ] **Step 1: 编写失败测试**

新增预检测试，替换 `ArkVlmClient.ask_images` 或文本请求入口，断言预检通过统一 SDK 客户端发送“请只回复 ok”，成功时返回模型名，异常时返回脱敏错误。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_api.py -q`

Expected: FAIL，原因是 `check_vlm()` 仍直接使用 `httpx`。

- [ ] **Step 3: 实现预检复用**

删除 `preflight.py` 的 VLM HTTP payload/header 代码，构造 `ArkVlmClient` 并调用统一文本请求方法；保留现有预检返回结构。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_api.py -q`

Expected: PASS。

### Task 3: 让离线脚本复用统一客户端

**Files:**
- Modify: `make_labels/tests/test_teacher_vlm_labeler.py`
- Modify: `make_labels/scripts/teacher_vlm_labeler.py`

- [ ] **Step 1: 编写失败测试**

新增异步 SDK 复用测试，断言 `call_vlm()` 使用 `ArkVlmClient`，返回可写入 `raw_vlm` 的字典和文本；确保旧的 VLM `post_json_with_retries()` 不再存在，而 detector 专用 `post_detect_json_with_retries()` 不变。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_teacher_vlm_labeler.py -q`

Expected: FAIL，原因是离线 VLM 仍通过 `requests.post()`。

- [ ] **Step 3: 实现离线 SDK 复用**

将离线 `call_vlm()` 改为调用 `ArkVlmClient`，同步批处理入口用 `asyncio.run()` 驱动；删除只服务于旧 VLM HTTP 请求的重试函数与相关认证 header。保留 detector 的 `requests` 依赖和重试实现。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_teacher_vlm_labeler.py -q`

Expected: PASS。

### Task 4: 更新配置与使用说明

**Files:**
- Modify: `make_labels/config.example.toml`
- Modify locally, ignored by Git: `make_labels/config.toml`
- Modify: `make_labels/README.md`

- [ ] **Step 1: 更新公开样例**

将 `[vlm].api_url` 说明为 SDK `base_url`，样例 URL 不带 `/responses`，密钥继续使用占位符；README 说明主服务、预检和离线脚本均通过 OpenAI SDK 调用 Ark Responses API。

- [ ] **Step 2: 更新本地敏感配置**

将被 Git 忽略的 `config.toml` 改为用户提供的 Ark base URL、模型和真实 API key。真实 key 不出现在命令输出、diff、日志、测试或文档中。

### Task 5: 自动化与真实 Smoke 验证

**Files:**
- Modify: `make_labels/docs/teacher-behavior-api-v6-harness.md`

- [ ] **Step 1: 安装并核对依赖**

Run: `conda run -n make_label python -m pip install -r make_labels/requirements.txt`

Expected: OpenAI SDK 安装成功，`pip check` 无依赖冲突。

- [ ] **Step 2: 运行完整自动化验证**

Run: `cd make_labels && conda run -n make_label python -m pytest tests -q`

Run: `cd make_labels && conda run -n make_label python -m compileall -q app scripts tests`

Run: `cd make_labels && conda run -n make_label python -m pip check`

Run: `cd make_labels && conda run -n make_label python -m app.main --help`

Run: `cd make_labels && conda run -n make_label python -m scripts.teacher_vlm_labeler --help`

Expected: 全部退出码为 0。

- [ ] **Step 3: 使用真实课堂图片调用 VLM**

从 Git 忽略的本地课堂图片中选择一张，通过本地 `config.toml` 构造 `ArkVlmClient` 并调用指定模型。仅记录 HTTP/SDK 成功状态和解析后的标签摘要，不保存或输出 API key、Base64、完整原始响应。

- [ ] **Step 4: 更新 Harness**

记录 OpenAI SDK 版本、Ark base URL 的脱敏描述、指定模型、自动化测试数量和真实 VLM smoke 的脱敏结果。

### Task 6: 安全检查、提交与推送

**Files:**
- Inspect: all staged files

- [ ] **Step 1: 检查差异与敏感信息**

Run: `git diff --check`

Run: `git status --short`

扫描 staged diff，确认不包含真实 API key、内网主机、图片 Base64、课堂图片或完整 VLM 响应。

- [ ] **Step 2: 重新运行最终验证**

再次执行 Task 5 的完整自动化验证，使用本轮新鲜输出作为提交依据。

- [ ] **Step 3: 中文规范提交**

Run: `git add docs/superpowers/plans/2026-08-17-openai-sdk-vlm-migration.md make_labels`

Run: `git commit -m "feat: 使用 OpenAI SDK 调用 VLM"`

- [ ] **Step 4: 推送并核对远端**

Run: `git push origin main`

Run: `git ls-remote origin refs/heads/main`

Expected: 远端 `main` 指向新提交。

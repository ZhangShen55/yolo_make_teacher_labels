# 新版教师行为接口适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `make_labels` 的主服务和离线脚本切换到新版教师行为契约，并用真实 `8871` 响应完成受控联调。

**Architecture:** `app/detector.py` 作为唯一接口适配器，负责 HTTP 重试、响应状态校验、`100` 主体框选择和 `201-204` 行为汇总。主流水线与离线脚本消费同一个解析结果；图像模块负责将全部中文初检标签绘制在主体框上方，VLM 只负责最终行为复核。

**Tech Stack:** Python 3.12、httpx、requests、Pillow、Pytest、FastAPI

---

### Task 1: 新版响应解析和主体框

**Files:**
- Modify: `make_labels/app/models.py`
- Modify: `make_labels/app/detector.py`
- Modify: `make_labels/tests/test_detector.py`

- [x] **Step 1: 写新版 fixture 的失败测试**

覆盖 `100` 主体框、`201=sit`、`202=stand`、`203=bbwriting`、`204=teach`、行为框为 `null`、多主体稳定排序、姿态冲突复核和 `205` 契约错误。

- [x] **Step 2: 运行定向测试并确认因旧映射和旧选框方式失败**

Run: `cd make_labels && conda run -n make_label python -m pytest tests/test_detector.py -q`

- [x] **Step 3: 实现单一新版解析器**

解析结果必须携带主体框、初检标签、原始类别、主体置信度、原始检测元数据和 `needs_review`；行为命中以 `ObjectCount>0` 为准。

- [x] **Step 4: 运行定向测试直到通过**

### Task 2: 状态校验和有限重试

**Files:**
- Modify: `make_labels/app/detector.py`
- Modify: `make_labels/tests/test_detector.py`

- [x] **Step 1: 写根级/单图状态、缺图、重复 ID 和 HTTP 重试失败测试**

覆盖总计 3 次请求、`429/500/503`、连接超时、`Retry-After` 上限，以及 `422` 和业务失败不重试。

- [x] **Step 2: 运行测试确认失败**

- [x] **Step 3: 实现响应校验和异步重试**

- [x] **Step 4: 运行定向测试直到通过**

### Task 3: 中文标签始终位于框上方

**Files:**
- Modify: `make_labels/app/imaging.py`
- Modify: `make_labels/tests/test_imaging.py`

- [x] **Step 1: 写中文文本、分隔符、框上位置和顶部画布失败测试**

- [x] **Step 2: 运行测试确认旧版中心文字失败**

- [x] **Step 3: 实现 `站立 | 板书 | 讲授` 框上渲染**

顶部不足时仅扩展 VLM 预览画布；最终 YOLO 坐标仍使用原图。

- [x] **Step 4: 运行定向测试直到通过**

### Task 4: VLM 与主流水线

**Files:**
- Modify: `make_labels/app/vlm_labeler.py`
- Modify: `make_labels/app/pipeline.py`
- Modify: `make_labels/tests/test_vlm_labeler.py`
- Modify: `make_labels/tests/test_job_runtime.py`

- [x] **Step 1: 写提示词和元数据失败测试**

提示词必须说明框上中文标签是可增删的初检候选；流水线必须使用 `100` 框并保存完整 detector 元数据。

- [x] **Step 2: 运行测试确认失败**

- [x] **Step 3: 更新提示词、流水线和失败分类**

- [x] **Step 4: 运行主项目测试直到通过**

### Task 5: 同步离线脚本

**Files:**
- Modify: `make_labels/scripts/teacher_vlm_labeler.py`
- Modify: `make_labels/tests/test_teacher_vlm_labeler.py`

- [x] **Step 1: 写离线脚本复用新版解析器的失败测试**

- [x] **Step 2: 运行测试确认失败**

- [x] **Step 3: 删除旧枚举和旧行为框选框逻辑，复用 `app.detector`**

- [x] **Step 4: 运行完整 `make_labels` 测试**

### Task 6: 配置、联调和提交

**Files:**
- Modify: `make_labels/config.example.toml`
- Modify: `make_labels/README.md`
- Modify locally only: `make_labels/config.toml`

- [x] **Step 1: 更新脱敏样例和运行文档**

- [x] **Step 2: 将被忽略的本地配置切换到目标 `8871` 实例**

- [x] **Step 3: 选择一张本地课堂图片调用新版接口**

只报告响应结构和字段，不提交图片、Base64、真实配置或原始响应。

- [x] **Step 4: 运行两项目完整测试、CLI、编译和安全扫描**

- [x] **Step 5: 中文 Conventional Commit 并推送 `main`**

# 双 FastAPI 项目目录整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将标签制作和标签审核工具安全整理为同仓库内两个可独立运行的 FastAPI 项目，并记录新版教师行为接口迁移契约。

**Architecture:** 仓库根目录只负责项目导航和安全边界；两个子项目各自拥有 `app` 包、测试、依赖和运行说明。目录迁移保持业务逻辑不变，新接口适配仅形成后续实施文档。

**Tech Stack:** Python 3.12、FastAPI、Uvicorn、Pytest、Pillow、httpx、Git

---

### Task 1: 建立安全仓库基线

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `make_label/config.example.toml`
- Create: `docs/superpowers/specs/2026-08-12-repository-restructure-design.md`
- Create: `docs/superpowers/plans/2026-08-12-repository-restructure.md`

- [ ] **Step 1: 验证原始测试基线**

Run:

```bash
conda run -n make_label python -m pytest make_label/tests -q
conda run -n label_review python -m pytest app/tests -q
python -m pytest tests -q
```

Expected: `67 passed`、`21 passed`、`5 passed`。

- [ ] **Step 2: 初始化仓库并设置本地身份**

```bash
git init -b main
git config user.name "zhangshen55"
git config user.email "865325136@qq.com"
git remote add origin git@github.com:ZhangShen55/yolo_make_teacher_labels.git
```

- [ ] **Step 3: 验证忽略和暂存边界**

确认 `config.toml`、数据集、日志、临时帧和 `.codex` 为 ignored；暂存源码后执行 `git diff --cached --check`，并扫描 staged 文件名和敏感特征。

- [ ] **Step 4: 提交并推送基线**

```bash
git commit -m "chore: 建立教师行为标注项目基线"
git push -u origin main
```

Expected: 远端 `main` 指向本地基线提交。

### Task 2: 整理两个独立 FastAPI 项目

**Files:**
- Move: `make_label/` to `make_labels/`
- Move: `make_labels/make_label/` to `make_labels/app/`
- Move: `app/` to `review_labels/`
- Move: `review_labels/label_review/` to `review_labels/app/`
- Move: `scripts/teacher_vlm_labeler.py` to `make_labels/scripts/teacher_vlm_labeler.py`
- Move: `tests/test_teacher_vlm_labeler.py` to `make_labels/tests/test_teacher_vlm_labeler.py`
- Modify: both projects' imports, static paths, tests and README files

- [ ] **Step 1: 执行纯目录移动并观察测试失败**

Run both test suites from their new project directories. Expected: imports and old hard-coded paths fail, proving the migration checks cover the renamed structure.

- [ ] **Step 2: 更新制作服务导入和测试路径**

将外部 `make_label` 导入改为独立项目内的 `app` 包；将静态源码检查改为基于测试文件位置定位；不修改业务实现。

- [ ] **Step 3: 更新审核服务导入、静态资源和测试路径**

使用包内相对导入，将静态资源放入 `review_labels/app/static`，让测试基于 `__file__` 寻址；不修改审核行为。

- [ ] **Step 4: 更新运行文档并验证**

```bash
cd make_labels && conda run -n make_label python -m pytest tests -q
cd review_labels && conda run -n label_review python -m pytest tests -q
cd make_labels && conda run -n make_label python -m app.main --help
cd review_labels && conda run -n label_review python -m app.main --help
```

Expected: `72 passed`、`21 passed`，两个 CLI 均返回帮助且退出码为 0。

- [ ] **Step 5: 提交并推送结构调整**

```bash
git commit -m "refactor: 将两个服务整理为独立 FastAPI 项目"
git push origin main
```

### Task 3: 记录新版接口迁移契约

**Files:**
- Create: `make_labels/docs/teacher-behavior-api-v6-migration.md`
- Modify: `make_labels/README.md`

- [ ] **Step 1: 记录契约差异和目标数据流**

文档必须包含 `201=sit`、`202=stand`、`203=bbwriting`、`204=teach`、`100=主教师主体框`，以及“绘制全部中文初检标签后交给 VLM 复核”的目标流程。

- [ ] **Step 2: 记录实现和测试清单**

明确主体框选择、行为关联、中文展示、VLM 增删标签、状态码校验、元数据兼容、429/503 和回归 fixture；标注当前阶段尚未实施接口切换。

- [ ] **Step 3: 提交并推送文档**

```bash
git commit -m "docs: 记录新版教师行为接口适配方案"
git push origin main
```

### Task 4: 最终审计

- [ ] **Step 1: 重新运行全部独立测试和 CLI 检查**
- [ ] **Step 2: 执行 `git diff --check`、忽略检查和 staged/tracked 敏感特征扫描**
- [ ] **Step 3: 核对本地 `main`、`origin/main` 和三次提交历史一致**

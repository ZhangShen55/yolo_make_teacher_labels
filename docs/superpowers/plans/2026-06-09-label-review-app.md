# Label Review App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI + Canvas label review app under `app/` for viewing, editing, batching, and rejecting YOLO teacher behavior labels.

**Architecture:** Backend owns all filesystem reads and writes, including YOLO txt, `annotations.jsonl`, backups, and rejected moves. Frontend is framework-free HTML/CSS/JS using Canvas for single-image bbox editing and a paginated 10-image batch review grid.

**Tech Stack:** Python, FastAPI, Uvicorn, Pydantic, Pillow, pytest, vanilla JavaScript Canvas.

---

## File Structure

- Create `app/main.py`: FastAPI app and CLI entrypoint.
- Create `app/requirements.txt`: runtime and test dependencies.
- Create `app/README.md`: setup, conda env, startup, test, and dataset layout docs.
- Create `app/label_review/__init__.py`: package marker.
- Create `app/label_review/yolo.py`: YOLO parsing, writing, grouping, coordinate conversion, label validation.
- Create `app/label_review/annotations.py`: JSONL read/write/update/remove helpers.
- Create `app/label_review/dataset.py`: dataset loading, summaries, image lookup, pagination.
- Create `app/label_review/review_ops.py`: backup, save annotation, reject sample, atomic writes.
- Create `app/label_review/schemas.py`: Pydantic models.
- Create `app/static/index.html`: review UI shell.
- Create `app/static/style.css`: dense workbench styling.
- Create `app/static/app.js`: API client, list/batch/single modes, Canvas bbox editing.
- Create `app/tests/test_yolo.py`: unit tests for coordinates, labels, grouping.
- Create `app/tests/test_review_ops.py`: unit tests for save/reject/backup.
- Create `app/tests/test_api.py`: FastAPI integration tests.

## Tasks

### Task 1: Backend Core Tests

**Files:**
- Create: `app/tests/test_yolo.py`
- Create: `app/tests/test_review_ops.py`
- Create: `app/tests/test_api.py`

- [ ] Write tests for YOLO conversion, label validation, grouping same-coordinate multi-label rows, save operation, reject operation, pagination, and FastAPI endpoints.
- [ ] Run `python -m pytest app/tests -q` and verify it fails because implementation files do not exist.

### Task 2: Backend Core Implementation

**Files:**
- Create: `app/label_review/__init__.py`
- Create: `app/label_review/yolo.py`
- Create: `app/label_review/annotations.py`
- Create: `app/label_review/dataset.py`
- Create: `app/label_review/review_ops.py`
- Create: `app/label_review/schemas.py`

- [ ] Implement YOLO parse/write/coordinate conversion and strict label validation.
- [ ] Implement JSONL read/write/update/remove with atomic replacement.
- [ ] Implement dataset scanning, summary, image detail, pagination, and batch rows.
- [ ] Implement first-write backup creation.
- [ ] Implement annotation save updating both txt and JSONL.
- [ ] Implement reject moving image, label txt, optional raw VLM JSON, active/rejected JSONL, and reject log.
- [ ] Run `python -m pytest app/tests -q` until backend tests pass.

### Task 3: FastAPI App

**Files:**
- Create: `app/main.py`

- [ ] Implement CLI `--dataset`, static file serving, and endpoints from the design doc.
- [ ] Add CORS-free local static frontend serving.
- [ ] Run `python -m pytest app/tests/test_api.py -q` and verify API tests pass.

### Task 4: Frontend

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/style.css`
- Create: `app/static/app.js`

- [ ] Implement single-image mode with image canvas, bbox draw, drag, resize handles, label controls, save, save-next, reject, reset.
- [ ] Implement batch mode with 10 cards per page, bbox overlay, label controls, save, reject, enter-detail.
- [ ] Implement search, label filter, `needs_review` filter, previous/next, and keyboard shortcuts.
- [ ] Use `/api/images/{image_id}/file` for images and backend APIs for all writes.

### Task 5: Environment and Docs

**Files:**
- Create: `app/requirements.txt`
- Create: `app/README.md`

- [ ] Create conda env `label_review` if missing.
- [ ] Install dependencies into `label_review`.
- [ ] Document setup, launch, dataset format, and tests.

### Task 6: Verification

**Files:**
- Existing: `测试数据/teacher-vlm-labels`

- [ ] Run all pytest tests inside `label_review`.
- [ ] Launch app against `../测试数据/teacher-vlm-labels`.
- [ ] Verify summary loads 95 active images.
- [ ] Verify batch API returns 10 images on page 1 and 5 on page 10.
- [ ] Use API-level temp copy checks to edit labels, edit bbox, and reject samples without damaging the original test dataset.
- [ ] Use browser/screenshot or API checks to confirm frontend loads.

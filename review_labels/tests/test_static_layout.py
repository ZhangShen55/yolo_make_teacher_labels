from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


def test_static_layout_has_fixed_viewport_and_scrollable_panels():
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "height: 100vh" in css
    assert "overflow: hidden" in css
    assert ".image-list-panel" in css and "min-height: 0" in css
    assert ".image-list" in css and "overflow-y: auto" in css
    assert "pageSizeSelect" in html


def test_batch_page_size_control_is_wired_in_javascript():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "pageSizeSelect" in js
    assert "state.pageSize = Number(el.pageSizeSelect.value)" in js


def test_dataset_folder_loader_is_available_in_ui():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "datasetPathInput" in html
    assert "loadDatasetBtn" in html
    assert "/api/dataset/load" in js


def test_image_list_has_own_pagination_controls():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "listPrevPageBtn" in html
    assert "listNextPageBtn" in html
    assert "listPageInfo" in html
    assert "state.listPage" in js
    assert "page_size=${state.listPageSize}" in js


def test_save_feedback_and_script_cache_busting_are_present():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "/app.js?v=" in html
    assert "保存失败：" in js
    assert "已保存 ${saved.file_name}" in js


def test_api_errors_are_human_readable_and_empty_batch_box_is_guarded():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "function formatApiError" in js
    assert "Array.isArray(detail)" in js
    assert "无 bbox，请进入精修模式" in js


def test_bbox_coordinates_are_rounded_before_save():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "app.js?v=20260609-rounded-bbox" in html
    assert "Math.round(Math.max" in js

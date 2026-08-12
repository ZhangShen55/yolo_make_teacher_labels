from PIL import Image

from app.imaging import build_display_text, render_box_preview, render_labeled_preview


def test_render_box_preview_draws_without_label_text(tmp_path):
    src = tmp_path / "src.jpg"
    out = tmp_path / "out.jpg"
    Image.new("RGB", (100, 80), "white").save(src)

    result = render_box_preview(src, out, [10, 10, 50, 60])

    assert result == out
    assert out.exists()


def test_build_display_text_uses_all_v6_chinese_labels_in_fixed_order():
    assert build_display_text(["teach", "stand", "bbwriting"]) == "站立 | 板书 | 讲授"


def test_render_labeled_preview_keeps_label_above_box_with_top_canvas(tmp_path):
    src = tmp_path / "src.png"
    out = tmp_path / "out.png"
    Image.new("RGB", (320, 180), "white").save(src)

    render_labeled_preview(src, out, [40, 2, 280, 170], ["stand", "bbwriting", "teach"])

    rendered = Image.open(out).convert("RGB")
    assert rendered.width == 320
    assert rendered.height > 180

    red_rows = []
    blue_rows = []
    for y in range(rendered.height):
        for r, g, b in (rendered.getpixel((x, y)) for x in range(rendered.width)):
            if r > 180 and g < 80 and b < 80:
                red_rows.append(y)
            if b > 120 and r < 120:
                blue_rows.append(y)
    assert red_rows
    assert blue_rows
    assert max(blue_rows) < min(red_rows)

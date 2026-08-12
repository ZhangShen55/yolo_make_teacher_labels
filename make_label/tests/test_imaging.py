from PIL import Image

from make_label.imaging import render_box_preview


def test_render_box_preview_draws_without_label_text(tmp_path):
    src = tmp_path / "src.jpg"
    out = tmp_path / "out.jpg"
    Image.new("RGB", (100, 80), "white").save(src)

    result = render_box_preview(src, out, [10, 10, 50, 60])

    assert result == out
    assert out.exists()

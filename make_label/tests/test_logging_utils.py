from make_label.logging_utils import redact_url


def test_redact_url_hides_sensitive_query_values():
    url = "https://vodserver.nuaa.edu.cn/a.mp4?auth_key=secret&x=1&token=abc"

    redacted = redact_url(url)

    assert "secret" not in redacted
    assert "abc" not in redacted
    assert "auth_key=%2A%2A%2A" in redacted or "auth_key=***" in redacted
    assert "x=1" in redacted

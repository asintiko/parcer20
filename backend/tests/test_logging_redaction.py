import httpx

from core.logging_config import _SecretRedactFilter


def test_redacts_telegram_token_from_httpx_url_argument():
    record = __import__("logging").LogRecord(
        name="httpx",
        level=20,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=(
            "POST",
            httpx.URL("https://api.telegram.org/bot123456:secret-token/sendMessage"),
            "HTTP/1.1",
            200,
            "OK",
        ),
        exc_info=None,
    )

    assert _SecretRedactFilter().filter(record) is True
    rendered = record.getMessage()

    assert "123456:secret-token" not in rendered
    assert "api.telegram.org/bot***REDACTED***/sendMessage" in rendered

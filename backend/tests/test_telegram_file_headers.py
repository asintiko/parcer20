from starlette.responses import FileResponse


def test_unicode_inline_filename_uses_rfc5987_header(tmp_path):
    path = tmp_path / "receipt.pdf"
    path.write_bytes(b"%PDF-1.4\n")

    response = FileResponse(
        path,
        filename="чек оплаты.pdf",
        content_disposition_type="inline",
    )

    header = response.headers["content-disposition"]
    assert header.startswith("inline; filename*=utf-8''")
    header.encode("latin-1")

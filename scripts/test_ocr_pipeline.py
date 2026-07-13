"""End-to-end OCR + DeepSeek-text прогон по сэмплам recipts/.

Запуск:
    cd /Users/kulacidmyt/Documents/parcer2.0
    DEEPSEEK_API_KEY=... python scripts/test_ocr_pipeline.py recipts
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from parsers.pdf_extractor import extract_text_from_image_path  # noqa: E402
from parsers.parser_orchestrator import ParserOrchestrator  # noqa: E402


def _glob_samples(folder: Path) -> list[Path]:
    samples: list[Path] = []
    for ext in ("*.jpeg", "*.jpg", "*.png"):
        samples.extend(folder.glob(ext))
    return sorted(samples)


def main(folder: str = "recipts") -> int:
    base = Path(folder)
    if not base.is_absolute():
        base = ROOT / folder
    samples = _glob_samples(base)
    if not samples:
        print(f"No samples in {base!s}")
        return 1

    orchestrator = ParserOrchestrator(db_session=None)
    passed = 0
    failed = 0
    rows: list[dict] = []

    for path in samples:
        text = extract_text_from_image_path(str(path))
        result = orchestrator.process(text) if text.strip() else None
        ok = bool(
            result
            and result.get("amount")
            and result.get("transaction_date")
        )
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {path.name}")
        print(f"  ocr_chars={len(text)} method={(result or {}).get('parsing_method')}")
        if result:
            print(
                f"  amount={result.get('amount')} {result.get('currency')} "
                f"date={result.get('transaction_date')} "
                f"operator={result.get('operator_raw')!r}"
            )
        else:
            print(f"  reason={orchestrator.last_rejection_reason}")
            preview = text[:200].replace("\n", " | ")
            print(f"  ocr_preview={preview!r}")
        rows.append(
            {
                "name": path.name,
                "ok": ok,
                "ocr_chars": len(text),
                "result": result,
                "rejection": orchestrator.last_rejection_reason,
            }
        )
        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    pct = (passed * 100 // total) if total else 0
    print(f"\n=== Summary: {passed}/{total} passed ({pct}%) ===")

    out_path = ROOT / "scripts" / "ocr_pipeline_report.json"
    out_path.write_text(
        json.dumps(rows, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    print(f"Report: {out_path}")

    return 0 if pct >= 80 else 2


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "recipts"
    sys.exit(main(folder))

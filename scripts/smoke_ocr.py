"""Smoke-only test: проверяем, что preprocess+multi-PSM выдает осмысленный текст
без зависимости от DeepSeek/Database. Печатает первые 200 символов и
кол-во распознанных латинских/кириллических букв.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from parsers.pdf_extractor import extract_text_from_image_path  # noqa: E402


def main() -> int:
    folder = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "recipts")
    samples = sorted(folder.glob("*.jpeg")) + sorted(folder.glob("*.jpg"))
    if not samples:
        print(f"No samples in {folder}")
        return 1

    rich = 0
    for p in samples:
        text = extract_text_from_image_path(str(p))
        letters = sum(c.isalpha() for c in text)
        digits = sum(c.isdigit() for c in text)
        ok = letters >= 30 and digits >= 5
        rich += int(ok)
        marker = "OK  " if ok else "WEAK"
        preview = text[:160].replace("\n", " | ")
        print(f"[{marker}] {p.name} chars={len(text)} letters={letters} digits={digits}")
        print(f"  {preview!r}")

    print(f"\n=== {rich}/{len(samples)} samples have rich OCR ({rich*100//len(samples)}%) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

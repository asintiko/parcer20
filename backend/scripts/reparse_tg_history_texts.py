"""Repair missing text in tg_chat_messages from stored raw_json.

Usage:
  python scripts/reparse_tg_history_texts.py
  python scripts/reparse_tg_history_texts.py --chat-id -1001234567890
  python scripts/reparse_tg_history_texts.py --limit 5000 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import or_

from database.connection import SessionLocal
from database.models import TgChatMessage
from services.message_utils import format_tdlib_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild tg_chat_messages.text from raw_json")
    parser.add_argument("--chat-id", type=int, default=None, help="Optional chat id filter")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to scan (0 = unlimited)")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts, do not update DB")
    parser.add_argument("--batch-size", type=int, default=500, help="Commit every N updates")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scanned = 0
    fixed = 0

    db = SessionLocal()
    try:
        query = db.query(TgChatMessage).filter(
            or_(TgChatMessage.text.is_(None), TgChatMessage.text == "")
        )
        if args.chat_id is not None:
            query = query.filter(TgChatMessage.chat_id == int(args.chat_id))
        query = query.order_by(TgChatMessage.id.asc())
        if int(args.limit or 0) > 0:
            query = query.limit(int(args.limit))

        rows = query.all()
        for row in rows:
            scanned += 1
            try:
                raw_payload = json.loads(row.raw_json or "{}")
            except Exception:
                continue
            formatted = format_tdlib_message(raw_payload) or {}
            text = str(formatted.get("text") or "").strip()
            if not text:
                continue
            if text == (row.text or ""):
                continue

            fixed += 1
            if not args.dry_run:
                row.text = text
                if fixed % max(1, int(args.batch_size)) == 0:
                    db.commit()

        if not args.dry_run:
            db.commit()
        print(
            f"Scan complete: scanned={scanned}, fixed={fixed}, "
            f"chat_id={args.chat_id if args.chat_id is not None else 'ALL'}, dry_run={args.dry_run}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

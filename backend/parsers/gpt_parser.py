"""Backward-compatible shim for legacy imports.

Use `/Users/kulacidmyt/Documents/parcer2.0/backend/parsers/ai_receipt_parser.py`
as the canonical runtime module.
"""

from parsers.ai_receipt_parser import ApplicationResolveSchema, GPTParser, ReceiptAiParser, TransactionSchema

__all__ = [
    "ApplicationResolveSchema",
    "GPTParser",
    "ReceiptAiParser",
    "TransactionSchema",
]

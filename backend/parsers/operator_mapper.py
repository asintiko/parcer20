"""
Operator name to application mapping module
Uses operator_reference as single source of truth.
"""
import re
from typing import Optional, List, Tuple, Dict

from sqlalchemy.orm import Session

from database.models import OperatorReference


class OperatorMapper:
    """
    Maps raw operator strings to applications using operator_reference.

    Cache layout: (id, operator_name_normalized, application_name, is_p2p)
    """

    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.mappings_cache: List[Tuple[int, str, str, bool]] = []
        self.refresh_cache()

    @staticmethod
    def normalize_operator(value: str) -> str:
        """
        Normalize operator text for matching:
        - uppercase
        - collapse whitespace
        - strip non-alphanumeric noise
        """
        if not value:
            return ""
        normalized = value.upper()
        normalized = re.sub(r"[\s\t\n]+", " ", normalized)
        normalized = re.sub(r"[^A-Z0-9 ]", " ", normalized)
        normalized = " ".join(normalized.split())
        return normalized

    def refresh_cache(self) -> None:
        """Reload cache from operator_reference (only active rows)."""
        rows = (
            self.db_session.query(OperatorReference)
            .filter(OperatorReference.is_active == True)  # noqa: E712
            .all()
        )
        self.mappings_cache = [
            (
                row.id,
                self.normalize_operator(row.operator_name),
                row.application_name,
                bool(row.is_p2p),
            )
            for row in rows
            if row.operator_name and row.application_name
        ]

    def map_operator_details(self, operator_raw: str) -> Optional[Dict]:
        """
        Return mapping details or None.
        Strategy:
        1. Exact normalized match
        2. Substring match; choose longest matched_operator_name
        """
        if not operator_raw:
            return None

        normalized_input = self.normalize_operator(operator_raw)
        if not normalized_input:
            return None

        exact_match: Optional[Tuple[int, str, str, bool]] = None
        best_substring: Optional[Tuple[int, str, str, bool]] = None
        best_len = -1

        for ref_id, pattern, app, is_p2p in self.mappings_cache:
            if not pattern:
                continue

            if normalized_input == pattern:
                exact_match = (ref_id, pattern, app, is_p2p)
                break

            if pattern in normalized_input:
                plen = len(pattern)
                if plen > best_len:
                    best_len = plen
                    best_substring = (ref_id, pattern, app, is_p2p)

        chosen = exact_match or best_substring
        if not chosen:
            return None

        ref_id, matched_operator_name, application_name, is_p2p = chosen
        match_type = "EXACT" if exact_match else "SUBSTRING"

        return {
            "reference_id": ref_id,
            "matched_operator_name": matched_operator_name,
            "application_name": application_name,
            "is_p2p": is_p2p,
            "match_type": match_type,
        }

    def map_operator(self, operator_raw: str) -> Optional[str]:
        """Backward compatible: return only application_name."""
        details = self.map_operator_details(operator_raw)
        return details["application_name"] if details else None

    def get_existing_applications(self) -> List[str]:
        """Distinct active application names."""
        apps = (
            self.db_session.query(OperatorReference.application_name)
            .filter(OperatorReference.is_active == True)  # noqa: E712
            .distinct()
            .all()
        )
        return [row[0] for row in apps]

    def get_candidate_examples(self, operator_raw: str, limit: int = 10) -> List[Dict]:
        """
        Return top similar reference rows for AI hinting.
        Simple similarity: substring + token overlap score.
        """
        normalized_input = self.normalize_operator(operator_raw)
        if not normalized_input:
            return []

        input_tokens = set(normalized_input.split())
        candidates: List[Tuple[float, Tuple[int, str, str, bool]]] = []

        for item in self.mappings_cache:
            ref_id, pattern, app, is_p2p = item
            if not pattern:
                continue

            score = 0.0
            if pattern == normalized_input:
                score += 100  # exact match bonus
            if pattern in normalized_input or normalized_input in pattern:
                score += len(pattern)

            pattern_tokens = set(pattern.split())
            overlap = len(input_tokens & pattern_tokens)
            score += overlap * 5

            if score > 0:
                candidates.append((score, item))

        candidates.sort(key=lambda t: (-t[0], -len(t[1][1]), t[1][0]))
        top = candidates[:limit]

        return [
            {
                "reference_id": ref_id,
                "matched_operator_name": pattern,
                "application_name": app,
                "is_p2p": is_p2p,
                "score": score,
            }
            for score, (ref_id, pattern, app, is_p2p) in top
        ]

"""Lightweight in-process metrics — counters, gauges, histograms.

No external dependency: keeps state in-memory, exposed via `/api/internal/metrics`
JSON endpoint. Designed as a stepping stone before switching to
`prometheus_client` once the env adds it to requirements.

Thread-safe (suitable for asyncio + threads). Across processes (multiple uvicorn
workers / celery workers) each process keeps its own snapshot — aggregation has
to happen at the shipper level (Loki / VictoriaMetrics / Promtail).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[float]] = defaultdict(list)
_started_at: float = time.time()

_HIST_MAX_SAMPLES = 1024


def _key(name: str, labels: Optional[Dict[str, Any]]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    if not labels:
        return name, tuple()
    norm = tuple(sorted((str(k), str(v)) for k, v in labels.items()))
    return name, norm


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def inc(name: str, value: float = 1, labels: Optional[Dict[str, Any]] = None) -> None:
    """Increment a counter."""
    k = _key(name, labels)
    with _lock:
        _counters[k] += value


def gauge(name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
    """Set a gauge."""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = value


def observe(name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
    """Record a histogram sample (caps to last N samples per series)."""
    k = _key(name, labels)
    with _lock:
        bucket = _histograms[k]
        bucket.append(value)
        if len(bucket) > _HIST_MAX_SAMPLES:
            del bucket[: len(bucket) - _HIST_MAX_SAMPLES]


# --------------------------------------------------------------------------- #
def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((len(s) - 1) * q))
    return s[max(0, min(idx, len(s) - 1))]


def snapshot() -> Dict[str, Any]:
    """Snapshot all metrics in a JSON-friendly shape."""
    with _lock:
        out_counters = []
        for (name, labels), v in _counters.items():
            out_counters.append({"name": name, "labels": dict(labels), "value": v})
        out_gauges = []
        for (name, labels), v in _gauges.items():
            out_gauges.append({"name": name, "labels": dict(labels), "value": v})
        out_histograms = []
        for (name, labels), values in _histograms.items():
            if not values:
                continue
            count = len(values)
            total = sum(values)
            out_histograms.append(
                {
                    "name": name,
                    "labels": dict(labels),
                    "count": count,
                    "sum": total,
                    "avg": total / count,
                    "p50": _quantile(values, 0.5),
                    "p95": _quantile(values, 0.95),
                    "p99": _quantile(values, 0.99),
                    "min": min(values),
                    "max": max(values),
                }
            )
    return {
        "uptime_seconds": time.time() - _started_at,
        "counters": out_counters,
        "gauges": out_gauges,
        "histograms": out_histograms,
    }


def reset() -> None:
    """Wipe all metrics. Useful for tests."""
    with _lock:
        _counters.clear()
        _gauges.clear()
        _histograms.clear()

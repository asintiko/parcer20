"""Process-local metrics mirrored to Redis for cross-worker aggregation.

No external dependency: keeps state in-memory, exposed via `/api/internal/metrics`
JSON endpoint. Designed as a stepping stone before switching to
`prometheus_client` once the env adds it to requirements.

Thread-safe and usable from asyncio, worker processes and parser threads.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
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
_REDIS_PREFIX = os.getenv("METRICS_REDIS_PREFIX", "tbsparcer:metrics:v1")
_redis_client = None
_redis_retry_after = 0.0
_redis_operations: queue.Queue = queue.Queue(maxsize=10_000)
_redis_worker_started = False


def _redis():
    global _redis_client, _redis_retry_after
    if str(os.getenv("METRICS_REDIS_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
        return None
    if time.monotonic() < _redis_retry_after:
        return None
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0"),
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                decode_responses=True,
            )
        except Exception:
            _redis_retry_after = time.monotonic() + 30
            return None
    return _redis_client


def _field(name: str, labels: Optional[Dict[str, Any]]) -> str:
    return json.dumps([name, sorted((str(k), str(v)) for k, v in (labels or {}).items())], separators=(",", ":"))


def _run_redis_worker() -> None:
    global _redis_client, _redis_retry_after
    while True:
        callback = _redis_operations.get()
        client = _redis()
        if client is not None:
            try:
                callback(client)
            except Exception:
                _redis_client = None
                _redis_retry_after = time.monotonic() + 30
        _redis_operations.task_done()


def _redis_call(callback) -> None:
    """Queue mirror writes so metrics never block an API event loop."""
    global _redis_worker_started
    if not _redis_worker_started:
        with _lock:
            if not _redis_worker_started:
                threading.Thread(
                    target=_run_redis_worker,
                    name="metrics-redis-writer",
                    daemon=True,
                ).start()
                _redis_worker_started = True
    try:
        _redis_operations.put_nowait(callback)
    except queue.Full:
        pass


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
    field = _field(name, labels)
    _redis_call(lambda client: client.hincrbyfloat(f"{_REDIS_PREFIX}:counters", field, value))


def gauge(name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
    """Set a gauge."""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = value
    field = _field(name, labels)
    _redis_call(lambda client: client.hset(f"{_REDIS_PREFIX}:gauges", field, value))


def observe(name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
    """Record a histogram sample (caps to last N samples per series)."""
    k = _key(name, labels)
    with _lock:
        bucket = _histograms[k]
        bucket.append(value)
        if len(bucket) > _HIST_MAX_SAMPLES:
            del bucket[: len(bucket) - _HIST_MAX_SAMPLES]
    field = _field(name, labels)
    digest = hashlib.sha256(field.encode()).hexdigest()[:24]

    def _record(client) -> None:
        pipe = client.pipeline(transaction=False)
        pipe.hset(f"{_REDIS_PREFIX}:histogram_registry", digest, field)
        pipe.lpush(f"{_REDIS_PREFIX}:histogram:{digest}", float(value))
        pipe.ltrim(f"{_REDIS_PREFIX}:histogram:{digest}", 0, _HIST_MAX_SAMPLES - 1)
        pipe.execute()

    _redis_call(_record)


# --------------------------------------------------------------------------- #
def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((len(s) - 1) * q))
    return s[max(0, min(idx, len(s) - 1))]


def snapshot(*, aggregate: bool = True) -> Dict[str, Any]:
    """Snapshot metrics; Redis values aggregate backend and Celery workers."""
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
    result = {
        "uptime_seconds": time.time() - _started_at,
        "counters": out_counters,
        "gauges": out_gauges,
        "histograms": out_histograms,
        "scope": "process",
    }
    if not aggregate:
        return result

    client = _redis()
    if client is None:
        return result
    try:
        counters = [
            {"name": json.loads(field)[0], "labels": dict(json.loads(field)[1]), "value": float(value)}
            for field, value in client.hgetall(f"{_REDIS_PREFIX}:counters").items()
        ]
        gauges = [
            {"name": json.loads(field)[0], "labels": dict(json.loads(field)[1]), "value": float(value)}
            for field, value in client.hgetall(f"{_REDIS_PREFIX}:gauges").items()
        ]
        histograms = []
        for digest, field in client.hgetall(f"{_REDIS_PREFIX}:histogram_registry").items():
            values = [float(v) for v in client.lrange(f"{_REDIS_PREFIX}:histogram:{digest}", 0, -1)]
            if not values:
                continue
            descriptor = json.loads(field)
            total = sum(values)
            histograms.append(
                {
                    "name": descriptor[0],
                    "labels": dict(descriptor[1]),
                    "count": len(values),
                    "sum": total,
                    "avg": total / len(values),
                    "p50": _quantile(values, 0.5),
                    "p95": _quantile(values, 0.95),
                    "p99": _quantile(values, 0.99),
                    "min": min(values),
                    "max": max(values),
                }
            )
        result.update(counters=counters, gauges=gauges, histograms=histograms, scope="redis_aggregate")
    except Exception:
        pass
    return result


def reset() -> None:
    """Wipe all metrics. Useful for tests."""
    with _lock:
        _counters.clear()
        _gauges.clear()
        _histograms.clear()

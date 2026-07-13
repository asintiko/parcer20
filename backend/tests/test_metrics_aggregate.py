from services import metrics


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def hset(self, *args):
        self.operations.append(("hset", args))
        return self

    def lpush(self, *args):
        self.operations.append(("lpush", args))
        return self

    def ltrim(self, *args):
        self.operations.append(("ltrim", args))
        return self

    def execute(self):
        for name, args in self.operations:
            getattr(self.redis, name)(*args)


class _FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}

    def hincrbyfloat(self, key, field, value):
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = float(bucket.get(field, 0)) + float(value)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]

    def pipeline(self, transaction=False):  # noqa: ARG002
        return _Pipeline(self)


def test_metrics_are_mirrored_without_blocking_and_aggregated(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setenv("METRICS_REDIS_ENABLED", "true")
    monkeypatch.setattr(metrics, "_redis_client", fake)
    monkeypatch.setattr(metrics, "_redis_retry_after", 0.0)
    metrics.reset()

    metrics.inc("receipts", labels={"status": "ok"})
    metrics.gauge("queue_depth", 3)
    metrics.observe("duration_ms", 12.5, labels={"queue": "fast"})
    metrics._redis_operations.join()

    snapshot = metrics.snapshot()
    assert snapshot["scope"] == "redis_aggregate"
    assert snapshot["counters"][0]["value"] == 1.0
    assert snapshot["gauges"][0]["value"] == 3.0
    assert snapshot["histograms"][0]["p95"] == 12.5

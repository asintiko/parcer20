from __future__ import annotations

from typing import Any


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.hashes: dict[str, dict[str, Any]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.ttls: dict[str, int] = {}

    def _has_key(self, key: str) -> bool:
        return key in self.values or key in self.hashes or key in self.sorted_sets

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        self.values[key] = value
        self.ttls[key] = int(ttl)
        return True

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            existed = False
            existed = key in self.values or existed
            existed = key in self.hashes or existed
            existed = key in self.sorted_sets or existed
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.ttls.pop(key, None)
            removed += int(existed)
        return removed

    async def hset(self, key: str, mapping: dict[str, Any]) -> int:
        target = self.hashes.setdefault(key, {})
        target.update(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, Any]:
        return dict(self.hashes.get(key, {}))

    async def expire(self, key: str, ttl: int) -> bool:
        if not self._has_key(key):
            return False
        self.ttls[key] = int(ttl)
        return True

    async def ttl(self, key: str) -> int:
        if not self._has_key(key):
            return -2
        return int(self.ttls.get(key, 3600))

    async def exists(self, key: str) -> int:
        return int(self._has_key(key))

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        target = self.sorted_sets.setdefault(key, {})
        target.update({member: float(score) for member, score in mapping.items()})
        return len(mapping)

    async def zrem(self, key: str, *members: str) -> int:
        target = self.sorted_sets.setdefault(key, {})
        removed = 0
        for member in members:
            if member in target:
                target.pop(member, None)
                removed += 1
        return removed

    async def zremrangebyscore(self, key: str, min_score: Any, max_score: Any) -> int:
        target = self.sorted_sets.setdefault(key, {})
        low = float("-inf") if str(min_score) == "-inf" else float(min_score)
        high = float("inf") if str(max_score) == "+inf" else float(max_score)
        to_remove = [member for member, score in target.items() if low <= float(score) <= high]
        for member in to_remove:
            target.pop(member, None)
        return len(to_remove)

    async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        target = self.sorted_sets.get(key, {})
        ordered = [member for member, _score in sorted(target.items(), key=lambda item: (item[1], item[0]), reverse=True)]
        if end < 0:
            end = len(ordered) - 1
        return ordered[start:end + 1]

    async def incr(self, key: str) -> int:
        current = int(self.values.get(key) or 0) + 1
        self.values[key] = current
        return current

    async def publish(self, _channel: str, _message: str) -> int:
        return 1


class FakeSyncRedis:
    def __init__(self, async_redis: FakeAsyncRedis) -> None:
        self.async_redis = async_redis

    def exists(self, key: str) -> int:
        return int(self.async_redis._has_key(key))

    def close(self) -> None:
        return None


def install_fake_auth_redis(monkeypatch):
    fake_async = FakeAsyncRedis()
    fake_sync = FakeSyncRedis(fake_async)

    async def fake_get_redis():
        return fake_async

    monkeypatch.setattr("services.auth_service.get_redis", fake_get_redis)
    monkeypatch.setattr("services.auth_bot_service.get_redis", fake_get_redis)
    monkeypatch.setattr("services.auth_bot_service._get_sync_redis", lambda: fake_sync)
    monkeypatch.setattr("api.routes.auth.get_redis", fake_get_redis)
    monkeypatch.setattr("api.routes.two_factor.get_redis", fake_get_redis)
    return fake_async, fake_sync

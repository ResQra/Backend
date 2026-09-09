"""Tiny TTL read cache for hot DynamoDB snapshot paths.

list_open_incidents fans out to 7 sequential GSI queries and is called
2-4x per board/summary/supervisor request; teams/shelters/areas full-scan
on every poll cycle. An 8-10s TTL kills most of that with zero contract
change. Writes invalidate explicitly in their repo (create/update), so the
worst staleness a coordinator ever sees is one poll interval — and every
mutation path invalidates eagerly anyway.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_store: dict[str, tuple[float, object]] = {}


def get(key: str, ttl_s: float, loader: Callable[[], T]) -> T:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and now - hit[0] < ttl_s:
            return _copy(hit[1])  # never hand out the live object
    value = loader()
    with _lock:
        _store[key] = (time.monotonic(), value)
    return _copy(value)


def _copy(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def invalidate(*keys: str) -> None:
    with _lock:
        for k in keys:
            _store.pop(k, None)


def clear() -> None:
    with _lock:
        _store.clear()

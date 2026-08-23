"""Process-local fallback stores used when DynamoDB is unavailable.

Keeps chat history + resident profiles in memory so the agent still has
conversation context during DB-less demos. Cleared on server restart;
DynamoDB becomes the source of truth once connected (routers try the DB
first and fall back here).
"""

import time
from collections import defaultdict

_MAX_MESSAGES = 20

_history: dict[str, list[dict]] = defaultdict(list)
_profiles: dict[str, dict] = {}


def append_message(user_id: str, role: str, content: str) -> None:
    h = _history[user_id]
    h.append({"user_id": user_id, "role": role, "content": content, "ts": time.time()})
    del h[:-_MAX_MESSAGES]


def get_history(user_id: str) -> list[dict]:
    return list(_history[user_id])


def get_profile(user_id: str) -> dict:
    return dict(_profiles.get(user_id) or {})


def update_profile(user_id: str, **fields) -> dict:
    p = _profiles.setdefault(user_id, {})
    p.update({k: v for k, v in fields.items() if v is not None})
    return dict(p)

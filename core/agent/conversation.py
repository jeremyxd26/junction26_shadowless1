"""In-memory conversations, each bound to one customer (agent-core.md section 7.6, contract 7.1).

Last 6 turns, 30 minutes. An id that is unknown, expired or owned by another customer starts a new
conversation, and earlier tool results are never reused (R4). Single process; a lock guards the map.
"""

from __future__ import annotations

import secrets
import string
import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_TURNS = 6
TTL_S = 30 * 60
_ALPHABET = string.ascii_lowercase + string.digits


def new_id(prefix: str) -> str:
    return prefix + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@dataclass
class Conversation:
    conversation_id: str
    customer_id: str
    updated: float
    language: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)  # question, calls, views, masked answer
    disclosed: bool = False   # the AI disclosure (or the introduction) was sent in this conversation (#420)


class ConversationStore:
    def __init__(self, ttl_s: float = TTL_S, clock=time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def resolve(self, conversation_id: str | None, customer_id: str) -> tuple[Conversation, bool]:
        """(conversation, reset). reset is True when an id was given but could not be continued."""
        now = self._clock()
        with self._lock:
            for cid in [k for k, c in self._items.items() if now - c.updated > self._ttl]:
                del self._items[cid]
            conv = self._items.get(conversation_id) if conversation_id else None
            if conv is not None and conv.customer_id == customer_id:
                conv.updated = now
                return conv, False
            conv = Conversation(new_id("conv_"), customer_id, now)
            self._items[conv.conversation_id] = conv
            return conv, conversation_id is not None

    def add_turn(self, conv: Conversation, turn: dict[str, Any]) -> None:
        with self._lock:
            conv.turns = (conv.turns + [turn])[-MAX_TURNS:]
            conv.updated = self._clock()

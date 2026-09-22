"""Associative Chinese→English recall: the seam for a small local model.

Substring search only finds words whose translation shares characters with the
query. The future implementation here embeds the query and compares it with
vectors precomputed for the most frequent words, so a query like "开心" can
also recall words defined with "快乐" or "愉悦" — semantic neighbours that no
LIKE search would surface. The model and its vectors stay on disk; nothing in
MiniDict talks to the network.

Wire it up in gui.main: MiniDictApp(root, associator=ModelAssociator(...)).
"""

from __future__ import annotations

from typing import Protocol


class Associator(Protocol):
    """English words related to a Chinese query, best first."""

    def associate(self, chinese: str, limit: int = 8) -> list[str]:
        """Return up to *limit* English words semantically close to *chinese*."""
        ...


class NullAssociator:
    """The no-op stand-in used until a model-backed implementation exists."""

    def associate(self, chinese: str, limit: int = 8) -> list[str]:
        return []

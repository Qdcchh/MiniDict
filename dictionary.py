"""Offline dictionary lookup backed by the local ECDICT SQLite database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent / "data" / "stardict.db"

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SENSE_SEPARATORS = re.compile(r"[，,、;；\n]")
_SENSE_PREFIX = re.compile(r"^(?:\[[^\]]*\]|\([^)]*\)|（[^）]*）|[a-z]+\.+\s*)+")
# ECDICT's frq is a frequency rank: smaller means more common, 0 or NULL unranked.
_UNRANKED = 2147483647


def contains_cjk(text: str) -> bool:
    """True when *text* holds a Chinese character, i.e. a reverse-lookup query."""
    return _CJK.search(text) is not None


def _has_whole_sense(translation: str, query: str) -> bool:
    """True when *query* appears as one complete sense inside *translation*."""
    for sense in _SENSE_SEPARATORS.split(translation):
        sense = _SENSE_PREFIX.sub("", sense).strip()
        if sense == query:
            return True
    return False


class DictionaryError(RuntimeError):
    """Raised when the dictionary database cannot be accessed."""


@dataclass(frozen=True)
class DictionaryEntry:
    """The fields MiniDict uses from one ECDICT entry."""

    word: str
    phonetic: str | None
    translation: str | None
    definition: str | None
    pos: str | None
    collins: int | None
    tag: str | None
    exchange: str | None


@dataclass(frozen=True)
class DictionaryCandidate:
    """One English word found for a Chinese query, with its translation."""

    word: str
    translation: str


class Dictionary:
    """Exact English lookups and Chinese→English lookups in an ECDICT database."""

    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a read-only connection; unusable databases raise here."""
        if not self.database_path.is_file():
            raise DictionaryError(
                f"Dictionary database not found: {self.database_path}"
            )
        database_uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(database_uri, uri=True)
        except sqlite3.Error as error:
            raise DictionaryError(
                f"Could not read dictionary database: {error}"
            ) from error
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def lookup(self, word: str) -> DictionaryEntry | None:
        """Return the exact entry for *word*, or ``None`` when it is unknown."""
        word = word.strip()
        if not word:
            return None
        with self._connect() as connection:
            try:
                row = connection.execute(
                    """
                    SELECT word, phonetic, translation, definition,
                           pos, collins, tag, exchange
                    FROM stardict
                    WHERE word = ? COLLATE NOCASE
                    LIMIT 1
                    """,
                    (word,),
                ).fetchone()
            except sqlite3.Error as error:
                raise DictionaryError(
                    f"Could not read dictionary database: {error}"
                ) from error

        if row is None:
            return None

        return DictionaryEntry(
            word=row["word"],
            phonetic=row["phonetic"],
            translation=row["translation"],
            definition=row["definition"],
            pos=row["pos"],
            collins=row["collins"],
            tag=row["tag"],
            exchange=row["exchange"],
        )

    def lookup_by_chinese(
        self, chinese: str, limit: int = 10
    ) -> list[DictionaryCandidate]:
        """Return English words whose translation mentions *chinese*, best first.

        The translation column has no index, so this scans it: the slow path.
        Entries where *chinese* stands as one whole sense rank above plain
        substring hits, then rarer words lose to more common ones.
        """
        query = chinese.strip()
        if not query or not contains_cjk(query):
            return []
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT word, translation, frq
                    FROM stardict
                    WHERE translation LIKE :pattern
                    ORDER BY CASE WHEN frq > 0 THEN frq ELSE 2147483647 END
                    LIMIT :pool
                    """,
                    {"pattern": f"%{query}%", "pool": max(4 * limit, 40)},
                ).fetchall()
            except sqlite3.Error as error:
                raise DictionaryError(
                    f"Could not read dictionary database: {error}"
                ) from error
        ranked = sorted(
            rows,
            key=lambda row: (
                not _has_whole_sense(row["translation"] or "", query),
                row["frq"] or _UNRANKED,
            ),
        )
        return [
            DictionaryCandidate(
                word=row["word"], translation=row["translation"] or ""
            )
            for row in ranked[:limit]
        ]

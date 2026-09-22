"""Offline dictionary lookup backed by the local ECDICT SQLite database."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent / "data" / "stardict.db"


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


class Dictionary:
    """Perform exact, case-insensitive lookups in an ECDICT database."""

    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    def lookup(self, word: str) -> DictionaryEntry | None:
        """Return the exact entry for *word*, or ``None`` when it is unknown."""
        word = word.strip()
        if not word:
            return None

        if not self.database_path.is_file():
            raise DictionaryError(
                f"Dictionary database not found: {self.database_path}"
            )

        database_uri = f"{self.database_path.resolve().as_uri()}?mode=ro"

        try:
            with closing(sqlite3.connect(database_uri, uri=True)) as connection:
                connection.row_factory = sqlite3.Row
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

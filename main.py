"""Command-line interface for MiniDict."""

from __future__ import annotations

from dictionary import Dictionary, DictionaryEntry, DictionaryError


def format_entry(entry: DictionaryEntry) -> str:
    """Format an entry for display in the command-line interface."""
    heading = entry.word
    if entry.phonetic:
        heading += f" /{entry.phonetic}/"

    sections = [heading]

    if entry.translation:
        sections.append(f"中文:\n{entry.translation}")

    if entry.definition:
        sections.append(f"English:\n{entry.definition}")

    metadata = []
    if entry.tag:
        metadata.append(f"Tags: {entry.tag.upper()}")
    if entry.collins:
        metadata.append(f"Collins: {entry.collins}")
    if metadata:
        sections.append("\n".join(metadata))

    return "\n\n".join(sections)


def run_cli(dictionary: Dictionary | None = None) -> None:
    """Run the interactive MiniDict prompt."""
    dictionary = dictionary or Dictionary()

    while True:
        try:
            word = input("Enter a word: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if word.lower() == "quit":
            break

        if not word:
            print("Please enter a word.\n")
            continue

        try:
            entry = dictionary.lookup(word)
        except DictionaryError as error:
            print(f"Dictionary error: {error}")
            break

        if entry is None:
            print(f'No entry found for "{word}".\n')
            continue

        print(f"\n{format_entry(entry)}\n")


if __name__ == "__main__":
    run_cli()

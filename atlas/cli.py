"""The command line: the two stages a person runs by hand.

Each subcommand parses arguments, calls one library function and prints what it
produced, so the behaviour worth testing lives in the library. An expected
failure, such as a missing file or an unset variable, is one line on stderr,
because a traceback tells someone who mistyped a path nothing to act on.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from atlas.contracts import Card
from atlas.extract import extract_cards
from atlas.ingest import read_markdown, read_pdf, write_markdown
from atlas.llm import Client, ModelConfig
from atlas.ontology import load as load_ontology


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return its exit code; 2 when no subcommand was given."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_usage(sys.stderr)
        return 2
    try:
        return arguments.run(arguments)
    # A source file the parser refuses and a failed model call both arrive as RuntimeError.
    except (OSError, ValueError, RuntimeError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas", description="Machine-readable scientific markup."
    )
    commands = parser.add_subparsers(dest="command")

    ingest = commands.add_parser("ingest", help="read PDFs and write their markdown rendering")
    ingest.add_argument("pdfs", nargs="+", type=Path, metavar="pdf")
    ingest.add_argument(
        "--out", type=Path, required=True, metavar="dir", help="directory to write markdown into"
    )
    ingest.set_defaults(run=_ingest)

    extract = commands.add_parser("extract", help="extract cards from one document")
    extract.add_argument("source", type=Path, metavar="markdown-or-pdf")
    extract.add_argument(
        "--out", type=Path, required=True, metavar="jsonl", help="file to write one card per line"
    )
    extract.set_defaults(run=_extract)
    return parser


def _ingest(arguments: argparse.Namespace) -> int:
    for source in arguments.pdfs:
        document = read_pdf(source)
        path = write_markdown(document, arguments.out)
        print(f"{document.id}\t{len(document.pages)}\t{path}")
    return 0


def _extract(arguments: argparse.Namespace) -> int:
    # The environment is read first so an unset variable fails before any file is opened.
    config = ModelConfig.from_env()
    source: Path = arguments.source
    document = read_pdf(source) if source.suffix.lower() == ".pdf" else read_markdown(source)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    client = Client(config)
    try:
        result = extract_cards(document, load_ontology(), client, run_id=run_id)
    finally:
        client.close()
    _write_jsonl(result.cards, arguments.out)
    print(
        f"cards {len(result.cards)}\tdropped {result.dropped}\t"
        f"needs review {result.needs_review}"
    )
    return 0


def _write_jsonl(cards: tuple[Card, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for card in cards:
            stream.write(card.model_dump_json() + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

"""The command line: run a configuration, write one to start from, or list the ones shipped.

Both subcommands are one library call -- `Pipeline.from_config(...).run(...)` and
`scaffold(...)` -- because what a run consists of is the configuration's business, the
store included: `--store` overrides the one it names, and names nothing when it does not.
Nothing here names a step or a type, and the one key of the state it reads is the store,
to say where the pass went; the summary counts whatever the steps left behind. An expected
failure, such as a missing file, an option no step takes or an unset variable, is one line
on stderr, since a traceback tells someone who mistyped a path nothing to act on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas import catalogue
from atlas.llm import Client, ModelConfig
from atlas.pipeline import ASK, Pipeline, summary
from atlas.scaffold import scaffold
from atlas.store import open_store


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return its exit code; 2 when no subcommand was given."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_usage(sys.stderr)
        return 2
    try:
        return arguments.run(arguments)
    # An unreadable input, a configuration that names nothing, a failed model call.
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Typed markup bound to its sources.")
    commands = parser.add_subparsers(dest="command")

    execute = commands.add_parser("run", help="run a pipeline configuration over some inputs")
    execute.add_argument("config", type=Path, metavar="config.yaml")
    execute.add_argument("inputs", nargs="+", type=Path, metavar="input")
    execute.add_argument(
        "--store", type=Path, default=None, metavar="dir",
        help="a directory of append-only logs to write into, overriding the configured store",
    )
    execute.set_defaults(run=_run)

    question = commands.add_parser(
        "ask", help="run the `ask` chain of a configuration over a store, and print the answer"
    )
    question.add_argument("config", type=Path, metavar="config.yaml")
    question.add_argument("question", metavar="question")
    question.add_argument(
        "--store", type=Path, default=None, metavar="dir",
        help="a directory of append-only logs to read, overriding the configured store",
    )
    question.set_defaults(run=_ask)

    start = commands.add_parser("init", help="write the skeleton of a project into a directory")
    start.add_argument("directory", type=Path, metavar="dir")
    start.set_defaults(run=_init)

    offered = commands.add_parser(
        "variants", help="list the architectures shipped with the library, or describe one"
    )
    offered.add_argument("id", nargs="?", default=None, metavar="id",
                         help="an architecture by its id (a18) or its number (18)")
    offered.add_argument("--json", action="store_true", dest="as_json",
                         help="print them as JSON, which is what an interface reads")
    offered.set_defaults(run=_variants)
    return parser


def _run(arguments: argparse.Namespace) -> int:
    # The configuration is read first, because reading it needs neither a key nor an input:
    # a step's misspelt option is then the error a run reports, instead of the unset
    # variable the next line raises on a machine where nobody has exported one yet.
    pipeline = Pipeline.from_config(arguments.config)
    client = Client(ModelConfig.from_env())
    context: dict = {"client": client}
    # Which store a run writes into is the configuration's, unless the command line names one.
    if arguments.store is not None:
        context["store"] = open_store({"jsonl": {"dir": str(arguments.store)}})
    try:
        state = pipeline.run(arguments.inputs, **context)
    finally:
        client.close()
    print("\t".join([summary(state), *_written(state)]))
    return 0


def _ask(arguments: argparse.Namespace) -> int:
    """Answer one question over a store, through the `ask` chain of a configuration.

    Nothing is ingested: the chain runs over a state that carries a question and no
    inputs, which is the shape a request has. The gap is printed on stderr when there
    is one, because "the graph holds nothing to answer this from" is not an answer and
    a caller piping stdout should not receive it as one.
    """
    pipeline = Pipeline.from_config(arguments.config, chain=ASK)
    client = Client(ModelConfig.from_env())
    context: dict = {"client": client, "question": arguments.question}
    if arguments.store is not None:
        context["store"] = open_store({"jsonl": {"dir": str(arguments.store)}})
    try:
        state = pipeline.run([], **context)
    finally:
        client.close()
    if state.get("gap"):
        print(f"atlas: {state['gap']}", file=sys.stderr)
    answer = state.get("answer")
    if answer is not None and answer.text:
        print(answer.text)
    return 0


def _written(state: dict) -> list[str]:
    """Where the pass was written and what the store recorded it cost, if it was written."""
    store = state.get("store")
    if store is None:
        return []
    fields = [] if store.location is None else [f"store {store.location}"]
    recorded = store.runs()
    return fields if not recorded else [*fields, f"{recorded[-1].seconds}s"]


def _variants(arguments: argparse.Namespace) -> int:
    """List the architectures, or one of them, as a table or as the JSON an interface reads."""
    chosen = [catalogue.get(arguments.id)] if arguments.id else list(catalogue.variants())
    if arguments.as_json:
        body = [one.model_dump() for one in chosen]
        print(json.dumps(body[0] if arguments.id else body, indent=2, ensure_ascii=False))
    else:
        print(catalogue.table(chosen))
    return 0


def _init(arguments: argparse.Namespace) -> int:
    for path in scaffold(arguments.directory):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

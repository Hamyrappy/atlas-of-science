"""The command line: run a configuration, or write one to start from.

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
import sys
from pathlib import Path

from atlas.llm import Client, ModelConfig
from atlas.pipeline import Pipeline, summary
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

    start = commands.add_parser("init", help="write the skeleton of a project into a directory")
    start.add_argument("directory", type=Path, metavar="dir")
    start.set_defaults(run=_init)
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


def _written(state: dict) -> list[str]:
    """Where the pass was written and what the store recorded it cost, if it was written."""
    store = state.get("store")
    if store is None:
        return []
    fields = [] if store.location is None else [f"store {store.location}"]
    recorded = store.runs()
    return fields if not recorded else [*fields, f"{recorded[-1].seconds}s"]


def _init(arguments: argparse.Namespace) -> int:
    for path in scaffold(arguments.directory):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

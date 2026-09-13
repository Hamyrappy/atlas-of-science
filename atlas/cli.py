"""The command line: run a configuration, or write one to start from.

Both subcommands are one library call -- `Pipeline.from_config(...).run(...)` and
`scaffold(...)` -- because what a run consists of is the configuration's business.
Nothing here names a step, a type or a key of the state: the summary counts whatever
the steps left behind. An expected failure, such as a missing file or an unset
variable, is one line on stderr, since a traceback tells someone who mistyped a path
nothing to act on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from atlas.llm import Client, ModelConfig
from atlas.pipeline import Pipeline, summary
from atlas.scaffold import scaffold
from atlas.store.jsonl import JsonlStore


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
        "--store", type=Path, default=Path("store"), metavar="dir",
        help="directory of append-only logs to write into (default: store)",
    )
    execute.set_defaults(run=_run)

    start = commands.add_parser("init", help="write the skeleton of a project into a directory")
    start.add_argument("directory", type=Path, metavar="dir")
    start.set_defaults(run=_init)
    return parser


def _run(arguments: argparse.Namespace) -> int:
    # The environment is read first so an unset variable fails before anything is written.
    client = Client(ModelConfig.from_env())
    try:
        pipeline = Pipeline.from_config(arguments.config)
        store = JsonlStore(arguments.store)
        state = pipeline.run(arguments.inputs, client=client, store=store)
    finally:
        client.close()
    print(f"{summary(state)}\tstore {store.directory}")
    return 0


def _init(arguments: argparse.Namespace) -> int:
    for path in scaffold(arguments.directory):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

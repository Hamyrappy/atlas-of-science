"""What `atlas init` writes: the four files a corpus of one's own needs before a run.

A project is a pack, a configuration naming the packs and the steps, a bank of
questions the markup will be scored against, and a note saying what the three are.
All four are data the owner of the corpus edits, so they are templates and not code,
and the pack here declares one placeholder type: the library ships no vocabulary, and
a skeleton that shipped six types would be shipping one.
"""

from __future__ import annotations

from pathlib import Path

PACK = """\
# The vocabulary this corpus is read under. Replace the placeholder with the types
# your questions need, mint the IRIs under a namespace you control, and keep one
# domain per file: packs are merged in the order the configuration names them.

prefixes:
  ex: https://example.org/ontology/example#

types:
  - name: Thing
    iri: ex:Thing
    description: Replace this with the first type your corpus is about.
    fields: [name, summary]

predicates:
  - name: relates_to
    iri: ex:relatesTo
    domain: Thing
    range: Thing
    description: Replace this with the first relation your questions ask about.
"""

PIPELINE = """\
# The run: which packs are loaded, and which steps execute in what order. Every name
# below is looked up in the step registry, so a step of your own goes in by being
# registered under a name and written here; options live under the name they belong to.

schema: pack.yaml

steps:
  - ingest_pdf
  - {render_markdown: {out: renderings}}
  - {extract_llm: {segment: page}}
  - relocate
  - validate
  - assert: {agent: run}
"""

QUESTIONS = """\
# What this markup is for. A question carries its acceptance criteria, so a run can be
# scored instead of admired; `dev` questions may steer the pack and the prompt, `test`
# questions are read only by the scoring code. See docs/evaluation.md.

version: 1

questions:
  - id: q1
    text: Replace this with a question the markup should answer.
    kind: fact
    split: dev
    expected_sources: []
    must_terms: []
"""

README = """\
# A corpus

- `pack.yaml` -- the types and predicates this corpus is read under.
- `pipeline.yaml` -- the packs to load and the steps to run.
- `questions.yaml` -- what the markup is for, and how a run is scored.

Run it:

```bash
export ATLAS_BASE_URL=... ATLAS_MODEL=... ATLAS_API_KEY=...
atlas run pipeline.yaml paper.pdf --store store/
```

The store is append-only: a second run lands under what is already recorded rather
than replacing it, and `store/assertions.jsonl` is the history of both.
"""

FILES = {
    "pack.yaml": PACK,
    "pipeline.yaml": PIPELINE,
    "questions.yaml": QUESTIONS,
    "README.md": README,
}


def scaffold(directory: Path | str) -> tuple[Path, ...]:
    """Write the four files of a new project into a directory, and return their paths.

    A file already there is never overwritten: the directory of a running corpus is
    the likeliest thing to be pointed at by mistake, and its pack is not replaceable.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    taken = [name for name in FILES if (directory / name).exists()]
    if taken:
        raise FileExistsError(f"{directory} already holds {', '.join(taken)}")
    written = []
    for name, body in FILES.items():
        path = directory / name
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return tuple(written)

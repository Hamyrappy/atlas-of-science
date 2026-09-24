"""What `atlas init` writes: the four files a corpus of one's own needs before a run.

A project is an ontology, a configuration naming it and the steps, a bank of questions
the markup will be scored against, and a note saying what the three are. All four are
data the owner of the corpus edits, so they are templates and not code, and the ontology
here declares one placeholder class and one relation: the library ships no vocabulary,
and a skeleton that shipped six classes would be shipping one.

The ontology is OWL 2 in Turtle, the format everything under `ontologies/` is written
in, so it opens in Protégé and it diffs. It imports the shared fields rather than
declaring its own `name`, because a field is a slot of a node and two IRIs for one slot
would be two slots.

The four below are the default and not the mechanism: `scaffold` writes whatever
mapping of relative name to text it is handed, so an application whose corpora have a
shape of their own passes that shape in rather than reimplementing the command. A name
may contain directories, which is the only layout rule there is.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

ONTOLOGY = """\
# The ontology this corpus is read under: OWL 2, in Turtle. Replace the placeholder
# class and relation with the ones your questions need, mint the IRIs under a namespace
# you control, and keep one domain per file -- a configuration can name several, and a
# file can import another with owl:imports.
#
# `atlas:name` is the word a configuration and a prompt use for a term; `atlas:fields`
# is what a node of the class records. Everything else is standard OWL, and anything
# OWL 2 can say here an engine will reason with: see docs/ontology.md.

@prefix ex:    <https://example.org/ontology/example#> .
@prefix field: <https://w3id.org/atlas-of-science/fields#> .
@prefix atlas: <https://w3id.org/atlas-of-science/substrate#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .

<https://example.org/ontology/example>
    a owl:Ontology ;
    owl:imports <https://w3id.org/atlas-of-science/fields> .

ex:Thing a owl:Class ;
    atlas:name "Thing" ;
    skos:definition "Replace this with the first class your corpus is about." ;
    atlas:fields ( field:name field:summary ) ;
    atlas:labelField field:name .

ex:relatesTo a owl:ObjectProperty ;
    atlas:name "relates_to" ;
    rdfs:domain ex:Thing ;
    rdfs:range ex:Thing ;
    skos:definition "Replace this with the first relation your questions ask about." .
"""

PIPELINE = """\
# The run: which ontology is loaded, and which steps execute in what order. Every name
# below is looked up in the step registry, so a step of your own goes in by being
# registered under a name and written here; options live under the name they belong to.
# `schema` may also say which OWL 2 profile the ontology must stay within, and which
# SHACL shapes the records are held to -- see docs/ontology.md.

schema: ontology.ttl
store: {jsonl: {dir: store}}

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
# scored instead of admired; `dev` questions may steer the ontology and the prompt, `test`
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

- `ontology.ttl` -- the OWL 2 ontology this corpus is read under.
- `pipeline.yaml` -- the ontology to load and the steps to run.
- `questions.yaml` -- what the markup is for, and how a run is scored.

Run it:

```bash
export ATLAS_BASE_URL=... ATLAS_MODEL=... ATLAS_API_KEY=...
atlas run pipeline.yaml paper.pdf
```

The store is append-only: a second run lands under what is already recorded rather
than replacing it, and `store/assertions.jsonl` is the history of both.
"""

FILES = {
    "ontology.ttl": ONTOLOGY,
    "pipeline.yaml": PIPELINE,
    "questions.yaml": QUESTIONS,
    "README.md": README,
}


def scaffold(directory: Path | str, templates: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Write a skeleton into a directory and return the paths written, in the order given.

    `templates` maps a relative name to the text to write under it, and defaults to the
    four files above. A file already there is never overwritten: the directory of a
    running corpus is the likeliest thing to be pointed at by mistake, and its ontology is
    not replaceable.
    """
    files = FILES if templates is None else templates
    directory = Path(directory)
    taken = [name for name in files if (directory / name).exists()]
    if taken:
        raise FileExistsError(f"{directory} already holds {', '.join(taken)}")
    written = []
    for name, body in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return tuple(written)

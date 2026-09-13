"""Artifact types exchanged between pipeline stages.

A stage is a pure function from artifacts to artifacts; the models below are the
only types that cross a stage boundary. They are therefore the one place where a
change breaks unrelated code: add fields freely, but renaming or removing one is
a breaking change for every stage and every artifact already on disk.

The central invariant of the markup — no provenance, no node — is enforced here
rather than in a prompt: a Card cannot be constructed without at least one Span,
and a Span cannot be constructed without the exact substring it points at.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


class Frozen(BaseModel):
    """Artifacts are values: immutable, compared by content, strict about types."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Page(Frozen):
    """One page of a document, in the text layer that spans are measured against."""

    number: int = Field(ge=1, description="1-based page number as printed by the parser")
    text: str


class Document(Frozen):
    """A source document after ingest.

    `pages[i].text` is fixed at ingest time and is the sole coordinate system for
    every span that will ever point into this document. Re-running ingest with a
    different parser produces a different document id, not a mutated document.
    """

    id: str
    source: str = Field(description="Path or URI the document was ingested from")
    pages: tuple[Page, ...] = Field(min_length=1)
    meta: dict[str, str] = Field(default_factory=dict)

    def page_text(self, number: int) -> str:
        for page in self.pages:
            if page.number == number:
                return page.text
        raise KeyError(f"{self.id} has no page {number}")


class Span(Frozen):
    """A verbatim fragment of a document, located by character offsets.

    Offsets index `Document.page_text(page)`. `text` is stored alongside them so a
    span can be re-verified against its source without loading the document, and
    so a drifted text layer is detectable rather than silently wrong.
    """

    doc_id: str
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _offsets_span_the_text(self) -> Span:
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        if self.end - self.start != len(self.text):
            raise ValueError("span offsets do not match the length of its text")
        return self


class Card(Frozen):
    """A typed statement extracted from one document.

    `type` and the keys of `fields` are constrained by the ontology the run was
    made with, not by this class: the ontology moves faster than the code. What is
    fixed here is that a card carries at least one span and names the ontology
    version it was written under, so a card written yesterday stays interpretable
    after today's ontology edit.
    """

    id: str
    type: str
    fields: dict[str, str] = Field(default_factory=dict)
    spans: tuple[Span, ...] = Field(min_length=1)
    run_id: str
    ontology_version: str


class Edge(Frozen):
    """A typed relation between two cards, itself supported by a span."""

    src: str
    predicate: str
    dst: str
    span: Span
    run_id: str
    ontology_version: str


class TypeDef(Frozen):
    """One node type of the ontology."""

    name: str
    parent: str | None = None
    fields: tuple[str, ...] = ()
    description: str = ""


class PredicateDef(Frozen):
    """One relation type, with the node types it may connect."""

    name: str
    domain: str
    range: str
    description: str = ""


class Ontology(Frozen):
    """The schema a run is made under: a frozen core plus a domain extension.

    The core is shared by every domain and changes rarely. The extension is
    produced per domain — by hand or automatically — and every extension type
    must descend from a core type, which is what keeps two domains comparable.
    `version` is the content hash of the source files; it travels on every card.
    """

    version: str
    types: tuple[TypeDef, ...]
    predicates: tuple[PredicateDef, ...]

    def type_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.types)

    def find_type(self, name: str) -> TypeDef | None:
        return next((t for t in self.types if t.name == name), None)

    def find_predicate(self, name: str) -> PredicateDef | None:
        return next((p for p in self.predicates if p.name == name), None)


class QuestionKind(str, Enum):
    """What a competency question asks for; retrieval is scored per kind."""

    FACT = "fact"
    AGGREGATE = "aggregate"
    COMPARISON = "comparison"


class CompetencyQuestion(Frozen):
    """A question the markup is expected to answer, with its acceptance criteria.

    `split` keeps the set honest: `dev` questions may steer the ontology, `test`
    questions are held out and only ever used to report a number.
    """

    id: str
    kind: QuestionKind
    question: str
    expected_docs: tuple[str, ...] = ()
    must_terms: tuple[str, ...] = ()
    split: Literal["dev", "test"] = "dev"


class QuestionSet(Frozen):
    """A versioned bank of competency questions for one domain."""

    version: str
    questions: tuple[CompetencyQuestion, ...]

    def split(self, name: Literal["dev", "test"]) -> tuple[CompetencyQuestion, ...]:
        return tuple(q for q in self.questions if q.split == name)


class Retrieved(Frozen):
    """One card returned by retrieval, with the score that ranked it."""

    card_id: str
    score: float


class RetrievalResult(Frozen):
    """What retrieval returns for one question, ranked best first."""

    question_id: str
    cards: tuple[Retrieved, ...] = ()
    run_id: str = ""


class Answer(Frozen):
    """A generated answer, with the cards it is allowed to have used."""

    question_id: str
    text: str
    citations: tuple[str, ...] = ()
    run_id: str = ""


class EvalReport(Frozen):
    """Metrics for one stage of one run, plus the samples behind them.

    Samples are kept because a number without the cases that produced it cannot be
    argued with — and the first question asked of any metric here is which cases
    it counted.
    """

    run_id: str
    stage: str
    metrics: dict[str, float]
    samples: tuple[dict[str, str], ...] = ()
    schema_version: int = SCHEMA_VERSION

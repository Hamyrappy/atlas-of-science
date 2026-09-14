"""The two typed things a schema can describe: a node, and a relation between nodes.

Neither class knows a type system. `type` and `predicate` are terms of whichever
schema was loaded -- an IRI, or a CURIE against that schema's prefixes -- and the
fields are whatever that schema declares, which is why both are plain strings and a
plain dict: the ontology moves faster than this file, and the core must stay
ignorant of it.

What is fixed here is evidence. Nothing exists without a span, and all the spans of
one object come from a single source, because a thing evidenced in two documents is
two things until something asserts they are one. A link carries its own id, a
content hash of what it relates and what it stands on, so two runs that find the
same relation on the same evidence write one link rather than two.
"""

from __future__ import annotations

import hashlib

from pydantic import Field, model_validator

from atlas.model.base import Frozen
from atlas.model.source import Span


class Evidenced(Frozen):
    """Whatever is claimed about the world, carrying the text it was claimed from."""

    id: str
    spans: tuple[Span, ...] = Field(min_length=1)
    schema_version: str = Field(description="Version of the schema the object was written under")

    @model_validator(mode="after")
    def _spans_come_from_one_source(self) -> Evidenced:
        sources = sorted({span.source_id for span in self.spans})
        if len(sources) > 1:
            raise ValueError(f"evidence from more than one source: {sources}")
        return self


class Node(Evidenced):
    """A typed thing, valid under the schema it names and located in the text."""

    type: str = Field(description="An IRI or a CURIE naming a type of the loaded schema")
    fields: dict[str, str] = Field(default_factory=dict)

    @property
    def ref(self) -> str:
        """A short name a reader can be shown and an answer can cite.

        `id` is a content hash: too long for prose and meaningless to a person, while
        a number minted over the current projection renumbers every node the next time
        a corpus is marked up. This is derived from the node alone -- the source it was
        read from and a stub of its own hash -- so the same claim on the same quote
        carries the same reference in every run, and a citation stays true.
        """
        return f"{self.spans[0].source_id}#{self.id[:6]}"

    def text(self) -> str:
        """Everything about this node that is worth matching text against.

        What was claimed and what the claim stands on: the field values, then the
        quotes. Indexing, ranking and prompting all want exactly this, and wrote it
        out separately until they disagreed.
        """
        return "\n".join([*self.fields.values(), *(span.text for span in self.spans)])


class Link(Evidenced):
    """A typed relation between two nodes, an object in its own right."""

    predicate: str = Field(description="An IRI or a CURIE naming a predicate of the schema")
    src: str
    dst: str
    fields: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def of(
        cls,
        predicate: str,
        src: str,
        dst: str,
        spans: tuple[Span, ...],
        schema_version: str,
        fields: dict[str, str] | None = None,
    ) -> Link:
        """Create a link under the id its content implies.

        The id hashes what the link relates and what it stands on, and not its
        fields, so annotating a link later does not turn it into a second link. The
        plain constructor exists for deserialising what this one wrote.
        """
        evidence = sorted(f"{s.source_id}:{s.segment}:{s.start}:{s.end}" for s in spans)
        material = "\x00".join([src, predicate, dst, *evidence])
        return cls(
            id=hashlib.sha256(material.encode("utf-8")).hexdigest()[:16],
            predicate=predicate,
            src=src,
            dst=dst,
            spans=spans,
            schema_version=schema_version,
            fields=fields or {},
        )

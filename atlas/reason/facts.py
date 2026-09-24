"""What an engine reasons over: facts about individuals, and the record of why each holds.

A node is an individual that its extraction asserted to be of one type; a link is an
individual related to another by one property. Those are the **given** facts, and each
keeps the id of the object that asserted it -- a node's id stands for "this node is of its
type", a link's id for "these two are related this way" -- so a derivation that cites them
cites something a reviewer can open and read the quote of.

Everything an engine adds is a **derived** fact, and it never exists without a
`Derivation`: the rule that produced it, in the OWL 2 RL rule table's own name and in a
word a reader can take in, the facts it was derived from, and the axiom of the ontology
that licensed the step. A consequence nobody can explain is a consequence nobody can
check, and one an answer quoted would be the system's own inference read back to the
reader as if a source had said it.

A contradiction is a `Clash`, not an exception: an individual inferred to be of two
disjoint classes, a relation asserted where the ontology forbids it. It carries its
premises the same way, because "which two claims cannot both be true" is exactly what a
reviewer needs, and an engine that stopped at the first one would hide the rest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from atlas.model import Frozen

TYPE = "rdf:type"
"""The predicate of a typing fact: the subject is an individual, the object a class name."""

SAME = "owl:sameAs"
"""The predicate of an identity fact: the two individuals are one."""


class Fact(Frozen):
    """One statement about individuals, and the id a derivation cites it by."""

    id: str
    subject: str
    predicate: str
    object: str
    derived: bool = False

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)

    @property
    def typing(self) -> bool:
        return self.predicate == TYPE


class Derivation(Frozen):
    """Why one derived fact holds: the rule, what it came from, and the axiom behind it.

    `link_id` names the fact in the vocabulary the rest of the library uses for relations;
    for a typing it is the id of the typing fact.
    """

    link_id: str
    rule: str
    rule_id: str = ""
    premises: tuple[str, ...]
    predicate: str = ""
    axiom: str = ""
    schema_version: str = ""

    @property
    def fact(self) -> str:
        return self.link_id

    def rests_on(self, withdrawn: Iterable[str]) -> bool:
        """Whether any of the premises is among what has been withdrawn."""
        return bool(set(self.premises) & set(withdrawn))


class Clash(Frozen):
    """Two or more facts the ontology says cannot all hold, and the axiom that says so."""

    rule: str
    rule_id: str
    subject: str
    premises: tuple[str, ...]
    axiom: str = ""
    detail: str = ""


def derived_id(subject: str, predicate: str, obj: str) -> str:
    """The id of a derived fact, from what it states and nothing else.

    Not from the derivation: a consequence that follows two ways is one consequence, and
    naming it after whichever path was found first would give it two ids on two runs.
    """
    material = "\x00".join(("derived", subject, predicate, obj))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def typing_id(node_id: str, type_name: str) -> str:
    """The id of the given fact that a node is of the type it was asserted with.

    The node's own id: a node asserts exactly one type, so the node *is* that fact, and a
    derivation citing it cites something a reviewer can open.
    """
    del type_name
    return node_id


__all__ = ["SAME", "TYPE", "Clash", "Derivation", "Fact", "derived_id", "typing_id"]

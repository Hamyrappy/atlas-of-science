# Evaluation

This document is the measurement contract. The code that computes these numbers does
not exist yet, and neither do its types: they were removed along with the old contracts
module rather than left standing as a claim that a stage exists. What remains is this
document and the `questions.yaml` that `atlas init` writes. The contract is written
first so that the metrics are fixed before any result is visible, which is the only
moment at which they can be chosen honestly.

## The unit of evaluation is a competency question

Quality of markup is not observable directly. What is observable is whether a question
the markup was built to answer can be answered from it. A competency question carries
its acceptance criteria with it: the sources the answer must come from
(`expected_sources`), the terms the answer must contain (`must_terms`), and a `kind`
that says whether one node suffices (`fact`) or the answer requires several
(`aggregate`, `comparison`). Questions are banked in a versioned file, and the version
is reported with every number.

The bank is split. `dev` questions may be looked at freely and may steer the pack, the
prompt and the retrieval. `test` questions are held out: they are read only by the
scoring code, and the only thing they ever produce is a reported number. A test question
that has been inspected while debugging is a dev question from that moment on. It does
not go back; write a new one instead.

## What is measured at each seam

Each seam is reported separately. A single blended score hides which step failed, and
the steps fail for unrelated reasons.

**Provenance.** The share of nodes whose spans still re-slice to their stored text:
`source.segment_text(span.segment)[span.start:span.end] == span.text`, evaluated at
scoring time against the source the store holds, not at construction time. The models
already guarantee the offsets are internally consistent, so a failure here means the
text layer drifted or the offsets were manufactured.

**Types.** The share of nodes and links with at least one violation under the schema of
the run, broken down by violation kind. The `validate` step already computes this for
what it refuses; scoring recomputes it over what was stored. See `docs/ontology.md`.

**Retrieval.** Hit rate on held-out questions: the share for which the ranked nodes
contain, within a fixed cut-off, a node evidenced by a source in `expected_sources`. The
cut-off is part of the number and is always reported with it. Score per kind of
question, because an aggregate question needs several of its nodes and a fact question
needs one.

**Answers.** Five binary checks per question, each reported as its own share: answered
(non-empty text that is not a refusal); cited (at least one citation, and every cited
node id exists in the store); spans re-verified (every cited node's spans re-slice at
scoring time); expected sources present (the cited nodes come from `expected_sources`);
required terms present (every entry of `must_terms` appears in the answer). An answer
that passes the first and fails the third is the failure mode worth catching, and
merging the five would hide it.

## Negative controls

Before any of the numbers above is believed, it is run against five deliberately
corrupted inputs. Each control names the metric it must move.

| Control | Corruption | Metric that must drop |
|---|---|---|
| Empty quote | span text replaced by whitespace | provenance share, node violations |
| Foreign quote | span points at a source that does not contain its text | provenance share |
| Reversed negation | a claim's polarity flipped, or a predicate swapped for its opposite, with the span left intact | answer checks |
| Duplicated entity | one entity emitted as two nodes with different ids | aggregate and comparison scores |
| Field with no source | a field filled with a value that appears nowhere in the node's spans | field grounding |

For each control, the metric, the direction and the minimum drop are written into the
control file before the run. A threshold picked after seeing the corrupted run measures
nothing but the willingness to pick it.

Two of these controls are pointed at gaps rather than at bugs. Reversed negation moves
nothing unless some check reads the span instead of the field text; field with no source
moves nothing unless field values are checked against the spans they claim to come from.
If those controls leave the numbers unchanged, the finding is about the metric suite, not
about the corrupted run.

A metric that survives corruption is worthless. If deliberately broken markup scores what
real markup scores, the metric is measuring a property the two share, such as fluency or
length, and not the property it is named after. The controls are far cheaper than a corpus
and they answer the first question any metric owes: what would make it fall?

## A number is reported with the cases behind it

A report carries its metrics and its samples together, and a report with no samples is
not a report. Every number is published with the agent and time the assertions were
written under, the schema version, the question set version, the denominator, the ids of
the cases counted, and the cut-off where one applies. Samples include failures; a
selection of flattering cases is worse than none, because it invites a conclusion the
number does not support. A metric with no cases attached cannot be argued with, and
anything that cannot be argued with does not survive contact with a new corpus.

The store makes this cheap rather than optional: every number above is computed over
assertions, each of which names its agent, its time, its evidence and what it superseded,
so the cases behind a metric are a query over the log and not a file somebody kept.

# Evaluation

This document is the measurement contract. The code that computes these numbers
does not exist yet; only `EvalReport` in `atlas/contracts.py` is in the repository
today. The contract is written first so that the metrics are fixed before any
result is visible, which is the only moment at which they can be chosen honestly.

## The unit of evaluation is a competency question

Quality of markup is not observable directly. What is observable is whether a
question the markup was built to answer can be answered from it. A
`CompetencyQuestion` carries its acceptance criteria with it: the documents the
answer must come from (`expected_docs`), the terms the answer must contain
(`must_terms`), and a `kind` that says whether one card suffices (`fact`) or the
answer requires several (`aggregate`, `comparison`). Questions are banked in a
versioned `QuestionSet`, and the version is reported with every number.

The bank is split. `dev` questions may be looked at freely and may steer the
ontology, the prompt and the retrieval. `test` questions are held out: they are
read only by the scoring code, and the only thing they ever produce is a reported
number. A test question that has been inspected while debugging is a dev question
from that moment on. It does not go back; write a new one instead.

## What is measured at each seam

Each seam is reported separately. A single blended score hides which stage failed,
and the stages fail for unrelated reasons.

**Provenance.** The share of cards whose spans still re-slice to their stored text:
`document.page_text(span.page)[span.start:span.end] == span.text`, evaluated at
scoring time against the document, not at construction time. The models already
guarantee the offsets are internally consistent, so a failure here means the text
layer drifted or the offsets were manufactured.

**Types.** The share of cards and edges with at least one violation under the
ontology of the run, broken down by violation kind. See `docs/ontology.md`.

**Retrieval.** Hit rate on held-out questions: the share for which the ranked cards
contain, within a fixed cut-off, a card from a document in `expected_docs`. The
cut-off is part of the number and is always reported with it. Score per
`QuestionKind`, because an aggregate question needs several of its cards and a fact
question needs one.

**Answers.** Five binary checks per question, each reported as its own share:
answered (non-empty text that is not a refusal); cited (at least one citation, and
every cited card id exists in the run); spans re-verified (every cited card's spans
re-slice at scoring time); expected documents present (the cited cards come from
`expected_docs`); required terms present (every entry of `must_terms` appears in
the answer). An answer that passes the first and fails the third is the failure
mode worth catching, and merging the five would hide it.

## Negative controls

Before any of the numbers above is believed, it is run against five deliberately
corrupted inputs. Each control names the metric it must move.

| Control | Corruption | Metric that must drop |
|---|---|---|
| Empty quote | span text replaced by whitespace | provenance share, card violations |
| Foreign quote | span points at a document that does not contain its text | provenance share |
| Reversed negation | a claim's polarity flipped, or `supports` swapped for `contradicts`, with the span left intact | answer checks |
| Duplicated entity | one entity emitted as two cards with different ids | aggregate and comparison scores |
| Field with no source | a field filled with a value that appears nowhere in the card's spans | field grounding |

For each control, the metric, the direction and the minimum drop are written into
the control file before the run. A threshold picked after seeing the corrupted run
measures nothing but the willingness to pick it.

Two of these controls are pointed at gaps rather than at bugs. Reversed negation
moves nothing unless some check reads the span instead of the field text; field
with no source moves nothing unless field values are checked against the spans they
claim to come from. If those controls leave the numbers unchanged, the finding is
about the metric suite, not about the corrupted run.

A metric that survives corruption is worthless. If deliberately broken markup
scores what real markup scores, the metric is measuring a property the two share,
such as fluency or length, and not the property it is named after. The controls are
far cheaper than a corpus and they answer the first question any metric owes:
what would make it fall?

## A number is reported with the cases behind it

`EvalReport` carries `metrics` and `samples` together, and a report with an empty
`samples` is not a report. Every number is published with the run id, the ontology
version, the question set version, the denominator, the ids of the cases counted,
and the cut-off where one applies. Samples include failures; a selection of
flattering cases is worse than none, because it invites a conclusion the number
does not support. A metric with no cases attached cannot be argued with, and
anything that cannot be argued with does not survive contact with a new corpus.

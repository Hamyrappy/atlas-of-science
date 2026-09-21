# How Atlas of Science is put together

One page, mostly pictures, for somebody who has just been handed this repository. It says
what the pieces are and how a corpus becomes an answer. Everything here is stated at length
elsewhere: `docs/architecture.md` is the reference, `CLAUDE.md` is the rules,
`docs/architectures/` is one specification per architecture.

---

## 1. The whole thing in one picture

```mermaid
flowchart TB
    SRC[("a corpus<br/>PDFs · text · tables")]

    subgraph BUILD["the chain that builds — steps:"]
        direction LR
        I["ingest<br/>the text layer is<br/>fixed here, for good"]
        E["extract<br/>a model is asked for<br/>a verbatim quote"]
        R["relocate<br/>the quote is found<br/>in the text, or dropped"]
        V["validate<br/>the pack judges<br/>the card"]
        L["relate<br/>relations, bound to<br/>their own quotes"]
        A["assert<br/>written as a claim,<br/>never as a row"]
        X["index"]
        I --> E --> R --> V --> L --> A --> X
    end

    subgraph STORE["the store — a history, not a table"]
        ASSERTIONS[("assertions<br/>append-only")]
        PROJ["nodes · links<br/>= current(history)"]
        ASSERTIONS --> PROJ
    end

    subgraph ASK["the chain that answers — ask:"]
        direction LR
        RANK["rank<br/>where to start"]
        WALK["walk<br/>one of fifteen ways<br/>of choosing a package"]
        ANS["answer<br/>from the package,<br/>or report the gap"]
        RANK --> WALK --> ANS
    end

    PACK[("ontology pack<br/>YAML · types · predicates<br/>hashed into schema_version")]

    SRC --> BUILD --> STORE --> ASK --> OUT(["an answer whose every<br/>claim names its quote"])
    PACK -.->|"loaded at run time"| BUILD
    PACK -.-> ASK

    MANIFEST[["architectures/aNN.yaml<br/>the manifest: which packs,<br/>which steps, in which order"]]
    MANIFEST -.-> BUILD
    MANIFEST -.-> ASK
```

Two things are worth pointing at in that picture, because they are what the library is for.

**The manifest is the only thing that differs between fifteen architectures.** There is no
branch anywhere under `atlas/` on which architecture is in use. By the time anything runs,
there is a pipeline and nothing else.

**The store is a history.** `nodes` and `links` are what `current` projects out of a body of
assertions. Nothing is updated and nothing is deleted, which is what lets a re-extraction
land *under* a human judgement instead of erasing it.

## 2. The six concepts, and nothing of any domain

```mermaid
erDiagram
    SOURCE ||--o{ SPAN : "cut out of"
    SPAN }o--|| NODE : "is the evidence for"
    SPAN }o--|| LINK : "is the evidence for"
    NODE ||--o{ LINK : "src / dst"
    ASSERTION }o--|| NODE : "claims"
    ASSERTION }o--|| LINK : "claims"
    ASSERTION }o--o| ASSERTION : "supersedes"
    SCHEMA ||--o{ NODE : "types"
    SCHEMA ||--o{ LINK : "declares the predicate of"

    SOURCE {
        string id
        string text_hash "names the frozen text layer"
        Segment_list segments "the sole coordinate system"
    }
    SPAN {
        int segment
        int start_end "offsets"
        string text "the quote, stored beside them"
    }
    NODE {
        string type "a term of the loaded pack"
        dict fields
        string schema_version
    }
    LINK {
        string predicate
        string src_dst
    }
    ASSERTION {
        Agent agent "who"
        string at "when"
        string supersedes "what it replaces"
    }
    SCHEMA {
        string version "the content hash of the packs"
    }
```

Not one of those boxes names a type, a field or a predicate of any subject. The types that
used to be built in live in `packs/ml_paper.yaml` now, and it is loaded only when a
configuration names it. `tests/test_substrate.py` is the standing proof: it runs the shipped
steps over an invented vocabulary, and a change under `atlas/` needed to make it pass means a
domain has leaked into the core.

## 3. The four invariants, as the places they are enforced

```mermaid
flowchart LR
    subgraph ONE["1 · No provenance, no node"]
        direction TB
        O1["Evidenced.spans has min_length=1"]
        O2["Span.of takes the text from the segment<br/>rather than being told it"]
        O3["a quote that cannot be located<br/>is dropped and counted"]
    end
    subgraph TWO["2 · The text layer is frozen at ingest"]
        direction TB
        T1["Source.segments[i].text is the only<br/>coordinate system there will ever be"]
        T2["Source.text_hash is checked when<br/>a rendering is read back"]
    end
    subgraph THREE["3 · Every object names its schema"]
        direction TB
        S1["schema_version = the content hash<br/>of the packs that were loaded"]
        S2["a node written last month stays<br/>interpretable after today's pack edit"]
    end
    subgraph FOUR["4 · Writing is asserting"]
        direction TB
        F1["nothing is updated, nothing deleted"]
        F2["a correction is a new Assertion<br/>naming the one it supersedes"]
        F3["the graph is current() over that history"]
    end
```

Break any of these and the markup stops being worth more than the text it came from. They
are the product, not a safety rail around it.

## 4. What a step is, and why that is the whole design

A step is a function from the state of a run plus its configured options to the keys it adds
to that state:

```mermaid
flowchart LR
    STATE1[("state in<br/>sources · schema · store · …")]
    STEP["register#40;relocate#41;<br/>requires: sources, statements, schema<br/>produces: nodes, unplaced, needs_review<br/>options: RelocateOptions"]
    STATE2[("state out<br/>#43; nodes · unplaced · needs_review")]
    CONF[["a line of pipeline.yaml<br/>relocate: #123; min_quote_chars: 16 #125;"]]
    STATE1 --> STEP --> STATE2
    CONF -.->|"options, refused when the<br/>file is read if they are wrong"| STEP
```

It does not know about a database, a web server or a queue: the store is handed to it.
Storage and IO live at the edge. Adding one is a module under `atlas/steps/`, an import line,
and a test — and a configuration that does not name it does not run it.

That is the whole reason fifteen architectures are maintainable. They are fifteen orderings
of forty-five steps, and the thing that varies between them is a file.

## 5. The rule every architecture obeys

```mermaid
flowchart LR
    Q(["a question"]) --> RANK["ranking<br/>finds where to start"]
    RANK -->|"hits"| SEL{"selection<br/>— the architecture —"}
    SEL -->|"bundle"| ANS["answering"]
    ANS --> OK(["an answer"])
    ANS --> GAP(["a gap, reported<br/>and never dressed up"])

    SEL -.->|"pulled in after the walk,<br/>whatever the budget did"| OBJ["the relation that<br/>argues the other way"]
    OBJ -.-> ANS
```

**An answer is built from a walked graph, not a list.** Ranking finds where to start; it does
not find an answer. Every `ask` chain contains a step producing a `Bundle` and ends in one
consuming it; a package that walked nothing is reported as a gap and never handed to a model;
and a relation named under `opposes` is pulled into the package after the walk, whatever the
budget did. `tests/test_catalogue.py` checks all three over every manifest, which is the only
way a rule stated in a document stays true.

## 6. Where to look

| I want to… | Read |
|---|---|
| run it | `README.md` |
| know what must not break | `CLAUDE.md` |
| continue somebody's work | `HANDOFF.md` |
| understand the store, provenance, versioning | `docs/architecture.md` |
| write an ontology pack | `docs/ontology.md` |
| choose between the fifteen | `docs/architectures/README.md` |
| know what is measured, and how | `docs/evaluation.md` |

```bash
atlas variants                       # the fifteen, from the manifests
atlas variants a18 --json            # one of them, as an interface reads it
atlas run architectures/a18.yaml corpus/*.pdf --store store/
atlas ask architectures/a18.yaml "which results hold under both protocols?" --store store/
```

# Handoff

For the next agent, or the next person, picking this up. `CLAUDE.md` says what must not break
and where things go; this file says **where the work stands, what standard the existing code was
held to, and the traps that have already been paid for.** Read both. Read this one second.

If you have never seen this repository before, read `docs/overview.md` first: six diagrams,
fifteen minutes, and everything below will mean something.

If you change something this file describes, change this file in the same commit. A handoff that
has quietly stopped being true is worse than none, because the next agent will trust it.

---

## 1. Where the work stands

Fifteen architectures ship, each as a manifest under `architectures/` with a specification under
`docs/architectures/`. `atlas variants` lists them; `tests/test_catalogue.py` checks every one of
them loads, resolves, and answers from a walked graph.

The substrate under them:

| | |
|---|---|
| **Metamodel** | Unchanged in its six concepts. Three fields were added — `TypeDef.disjoint_with`, `PredicateDef.characteristics`, `PredicateDef.inverse_of` — all additive. |
| **Graph** | `atlas/walk.py` (adjacency, bounded reach, simple paths, components, weights) and `atlas/steps/graph_expand.py` (`Bundle`, `expand`). |
| **Relations** | `relate_llm` / `relate` extract them; `assert` writes them; `map_rows` maps them out of tables. |
| **Stores** | memory, JSON lines, and SQLite with `reach` / `links_among` / `links_touching` pushed into queries. |
| **Packs** | `science_core`, `process`, `science_map`, `semantic_units`, `scierc`, `ml_paper`. Every combination passes the formal gate, and a test holds that. |
| **CLI** | `run`, `ask`, `init`, `variants`. |

**Not done, and deliberately so.** Canonicalisation of nodes across sources. The evaluation
harness (`docs/evaluation.md` states the contract; no code). A PostgreSQL store. Hybrid text
ranking. Nothing here has been run over a corpus large enough to rank the architectures against
each other — the scores in the manifests are an engineering judgement and say so everywhere they
appear. **Do not quietly upgrade them to measurements.**

---

## 2. The bar

This is the part that matters. The code in this repository is written to a standard that is easy
to lose one commit at a time, and each of these is visible in what is already there.

### A docstring says *why*, and names the failure it prevents

Not what the function does — the signature says that. The module docstring of
`atlas/steps/reconcile.py` explains why conditions are checked *before* the source; the one in
`atlas/steps/units.py` explains why an unknown polarity is `unsupported` and an unknown quantifier
is only `lossy`. Both were decisions that could have gone the other way, and a reader six months
from now has no way to recover them.

If you cannot name the failure a piece of code prevents, that is a sign the code is not needed.

### Honest naming, always

`atlas/steps/subgraph.py` is prize-collecting selection and says in its first paragraph that it is
a greedy growth and **not** an approximation with a bound — because a module named after PCST and
quietly doing something else makes every comparison against it meaningless.
`atlas/steps/paths.py` says its flow model is not PathRAG's published algorithm.
`atlas/steps/diffuse.py` says its damping value is a pilot starting point and not a claim about
anybody's tuning.

Whenever you implement something *like* a published method, say which part you took and which part
you did not.

### A test names a rule, not a function

Read `tests/test_units.py::test_an_unknown_polarity_is_unsupported_rather_than_lossy` or
`tests/test_map_rows.py::test_an_empty_key_never_joins`. Each test name is a sentence about
behaviour, and the module docstring of each test file states which rules are under test. A test
called `test_compare_works` would tell a future reader nothing about what broke.

Every architecture has at least one test of the thing that would make it worthless if it were
wrong. Find that thing first, then write the rest.

### No domain vocabulary under `atlas/`

Not a type, not a field, not a predicate, not a negation marker, not a salience category. Where a
step needs words of a language or of a field, they arrive as **options**, and the default is
usually empty — with nothing configured, `critique` finds no negations and `compile_units` calls
nothing exact. Failing closed is the right direction.

`tests/test_substrate.py` is the standing proof. If you have to touch `atlas/` to make it pass, a
domain has leaked in.

### Documents land in the same commit

New step, new option, new configuration key, changed behaviour — the document goes with it. Five
carry the project (`README.md`, `CLAUDE.md`, `docs/overview.md`, `docs/architecture.md`,
`docs/ontology.md` with `docs/evaluation.md`), plus one specification per architecture.

`docs/overview.md` is the one that goes stale without anybody noticing, because it is pictures:
a step added to a chain or a rule that moved changes a diagram there and nothing else complains.

Copy real output into documents rather than typing what it should say. The step tables in
`docs/architecture.md` were generated from the live registry; the options column is the string the
library itself prints when an option is wrong.

### Commit messages explain the decision

Look at `git log`. Each message says what problem the change addresses and which way a judgement
call went — not a list of files. They are long, and they are the cheapest documentation in the
repository.

---

## 3. Adding an architecture

1. **Read two existing specifications** in `docs/architectures/`, preferably the two nearest to
   what you are adding. They share eleven sections so that two can be read side by side.
2. **Find what is genuinely new.** Most architectures need one new step and reuse everything else.
   If you are writing a second walk, a second closure or a second answering rule, stop: those are
   shared on purpose.
3. **Write the step** in its own module under `atlas/steps/`, registered with `requires`,
   `produces` and an options model. Import it in `atlas/steps/__init__.py`.
4. **Write the tests** before the manifest. Start with the rule that would make the architecture
   worthless if it were wrong.
5. **Write the manifest** under `architectures/aNN.yaml`: `variant:` block, `schema:`, `steps:`,
   `ask:`. `tests/test_catalogue.py` will tell you if any of it does not resolve.
6. **Write the specification** under `docs/architectures/NN-name.md`, with the same eleven
   sections, and add it to that directory's `README.md` table.
7. `ruff check . && pytest`, then commit with a message that explains the decision.

The `variant:` block is read by `atlas/catalogue.py` and is what an interface shows. Fill in
`optimises`, `cost` and `differs` honestly — `cost` especially. An architecture with no stated cost
has not been thought about.

---

## 4. Standing checks

These run in the suite and are the ones that catch a regression in judgement rather than in code:

| Check | Where |
|---|---|
| The core carries no vocabulary | `tests/test_substrate.py` |
| Every manifest loads, resolves and answers from a walked graph | `tests/test_catalogue.py` |
| Every shipped pack passes the formal gate | `tests/test_formal_check.py` |
| An objection survives a budget | `tests/test_graph_expand.py`, `tests/test_graph_sql.py`, `tests/test_paths.py`, `tests/test_subgraph.py` |
| An ungrounded package is not answered | `tests/test_graph_answer.py` |
| Nothing derived, clustered or mapped is asserted without evidence | `tests/test_entail.py`, `tests/test_topics.py`, `tests/test_communities.py` |

---

## 5. Traps already paid for

Each of these was a real bug or a real mistake in this work. They are listed because the next
person will be tempted by exactly the same thing.

**A walk does not contain every relation.** `Walk` records how a node was *first* reached, so a
relation between two nodes that were both roots is in nobody's walk. `expand` originally collected
links from the walks and silently dropped exactly the relations a caller had already decided were
interesting. It now takes every relation among the nodes it holds.

**Label propagation collapses small graphs.** It was the first partition in
`atlas/steps/communities.py` and merged a few dozen nodes into one community — a true partition
and a useless one. Replaced with greedy modularity agglomeration, and
`test_two_cliques_joined_by_one_edge_come_apart` is the guard.

**A one-sided comparison finds that everything agrees.** `compare` originally read only the
baseline's conditions, so a baseline that recorded nothing concluded that every condition it knew
about matched. True, and the most misleading thing the step could say. It now reads both sides.

**Circular support survives a naive retraction.** Two derived relations can support each other
— A implies B by one rule, B implies A by another — so marking downwards from what was withdrawn
leaves the pair standing on nothing. `supported` builds the standing set *upwards* from what
somebody actually claimed.

**An empty key joins everything.** In `map_rows`, letting a blank identifier through as the empty
string collapses every such row into one node and makes every relation touching it a fully
provenanced claim that is entirely false. No key, no node, no relation.

**A withdrawal is an answer; an unreadable reply is not.** In `repair_llm`, treating both as
"stop" spent the whole budget on the first malformed reply. They are now distinguished.

**`PydanticUndefined` in a user-facing message.** `_takes` read `field.default`, which is a
sentinel for a field declared with a factory. The audience of that message is somebody editing a
configuration file; it now asks for the default properly.

---

## 6. Running it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # 634 tests, no network, no key
.venv/bin/python -m ruff check .       # what CI runs
.venv/bin/python -m atlas.cli variants
```

The package requires Python 3.12. If `pip install -e .` refuses, the interpreter is older than
that — build the virtual environment with `python3.12` explicitly.

Tests never reach the network and never need a key. A step that would call a model is tested with
a stub client that replays canned replies; `tests/conftest.py` holds the two stub steps and the
`science` fixture, which is the small body of markup — one claim, a position for and against, the
results and conditions behind each — that most graph tests walk.

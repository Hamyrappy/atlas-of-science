"""Tests for the shared folding: that relocation and indexing cannot drift apart.

The properties under test are the ones both callers rely on. Folding keeps a map back
onto the original offsets, which is what makes a relaxed search safe; normalising and
tokenising apply the same table, so a quote placed through one and indexed through the
other is still the same words; and nothing here alters the text it was given.
"""

from __future__ import annotations

from atlas.text import fold, normalise, to_original, tokenise


def test_folding_maps_every_character_back_onto_the_original() -> None:
    text = "The  model—a small one—reached 0.9"
    folded, offsets = fold(text)

    assert folded == "The model-a small one-reached 0.9"
    assert len(offsets) == len(folded)
    start, end = to_original(offsets, folded.index("model"), folded.index("model") + 5)
    assert text[start:end] == "model"


def test_normalising_folds_case_dashes_quotes_and_whitespace() -> None:
    assert normalise("  The “F‑score”  \n ROSE ") == 'the "f-score" rose'


def test_normalising_leaves_the_text_it_was_given_alone() -> None:
    text = "  Ragged   text\n"
    normalise(text)

    assert text == "  Ragged   text\n"


def test_the_same_words_tokenise_the_same_however_they_were_typed() -> None:
    assert tokenise("F‑score of the state–of–the–art model") == tokenise(
        "f-score of the STATE-OF-THE-ART model"
    )


def test_tokens_are_the_terms_of_the_normalised_text() -> None:
    assert tokenise("Don’t split it: 0.912 on held-out data.") == (
        "don't",
        "split",
        "it",
        "0",
        "912",
        "on",
        "held-out",
        "data",
    )


def test_a_quote_and_the_text_it_was_cut_from_tokenise_alike() -> None:
    """What the two callers actually share: the segment an index reads and the folded
    copy a relocation searches yield the same terms for the same region."""
    segment = "The  method—“ours”—reached 0.912."
    folded, _ = fold(segment)

    assert tokenise(folded) == tokenise(segment)

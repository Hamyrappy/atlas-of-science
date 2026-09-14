"""What more than one test module needs: a PDF, a configuration, and a stub extractor.

The PDF is built here rather than committed, so the suite carries no binary and the
text layer under test is the one this machine's parser produces. The stub stands in
for the one step that would need a model, and is registered under a name like any
other step: three modules run the same configured pipeline over different packs,
which is the claim the library makes about itself.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from atlas.steps import State, register
from atlas.steps.relocate import Statement


@pytest.fixture(scope="session")
def build_pdf() -> Callable[..., bytes]:
    """A function turning one tuple of lines per page, plus optional metadata, into PDF bytes."""

    def build(lines_per_page: tuple[tuple[str, ...], ...], **metadata: str) -> bytes:
        pdf = pymupdf.open()
        for lines in lines_per_page:
            page = pdf.new_page()
            page.insert_text((72, 72), list(lines), fontsize=11)
        if metadata:
            pdf.set_metadata(metadata)
        return pdf.tobytes()

    return build


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[[str, str], Path]:
    """A function writing a pack and a configuration naming it, returning the configuration."""

    def write(pack: str, steps: str) -> Path:
        (tmp_path / "pack.yaml").write_text(pack, encoding="utf-8")
        path = tmp_path / "pipeline.yaml"
        path.write_text(f"schema: pack.yaml\nsteps:\n{textwrap.dedent(steps)}", encoding="utf-8")
        return path

    return write


@register("stub_extract")
def stub_extract(state: State, *, types: dict[str, str] | None = None) -> State:
    """Stand in for a model: one statement per segment per configured type and field."""
    types = types or {"Thing": "name"}
    statements: list[Statement] = []
    for source in state["sources"]:
        for segment in source.segments:
            quote = segment.text.splitlines()[0]
            statements += [
                Statement(
                    source_id=source.id,
                    segment=segment.number,
                    type=name,
                    fields={field: quote},
                    quote=quote,
                )
                for name, field in types.items()
            ]
    return {"statements": tuple(statements), "malformed": 0}

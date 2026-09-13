"""Fixtures shared by the tests that need a PDF.

The PDF is built here rather than committed, so the suite carries no binary and
the text layer under test is the one this machine's parser produces.
"""

from __future__ import annotations

from collections.abc import Callable

import pymupdf
import pytest


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

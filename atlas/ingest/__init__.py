"""Ingest stage: source files in, Documents out."""

from __future__ import annotations

from atlas.ingest.markdown import read_markdown
from atlas.ingest.pdf import PAGE_MARKER, read_pdf, to_markdown, write_markdown

__all__ = ["PAGE_MARKER", "read_markdown", "read_pdf", "to_markdown", "write_markdown"]

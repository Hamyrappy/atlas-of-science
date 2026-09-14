"""The on-disk form of a Source: front matter plus one marked block per segment.

A rendering is written so that a person can read what was ingested and so that a later
run can start from it without the original file. Segment text is stored byte for byte,
because span offsets index it; the text hash is written alongside and checked on the way
back in, so an edited rendering is refused rather than silently shifting every span
already stored against it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from atlas.model import Segment, Source
from atlas.steps import State, register

SEGMENT_MARKER = "<!-- segment {number} -->"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n\n", re.DOTALL)
_MARKER = re.compile(r"^<!-- segment (\d+) -->\n", re.MULTILINE)


@register("render_markdown")
def render_markdown(state: State, *, out: str) -> State:
    """Write the rendering of every source of the run into one directory."""
    directory = Path(out)
    return {"renderings": tuple(write_markdown(s, directory) for s in state["sources"])}


@register("ingest_markdown")
def ingest_markdown(state: State) -> State:
    """Read every input of the run as a rendering written by `write_markdown`."""
    return {"sources": tuple(read_markdown(Path(path)) for path in state["inputs"])}


def to_markdown(source: Source) -> str:
    """Render a Source as front matter plus one marked block per segment."""
    # JSON string syntax is a subset of YAML's double-quoted scalar, so an id or a
    # path that YAML would otherwise read as a number or a mapping stays a string.
    front_matter = (
        "---\n"
        f"id: {json.dumps(source.id)}\n"
        f"origin: {json.dumps(source.origin)}\n"
        f"segments: {len(source.segments)}\n"
        f"text_hash: {json.dumps(source.text_hash)}\n"
        "---\n\n"
    )
    blocks = [
        f"{SEGMENT_MARKER.format(number=segment.number)}\n{segment.text}"
        for segment in source.segments
    ]
    return front_matter + "\n".join(blocks)


def write_markdown(source: Source, directory: Path) -> Path:
    """Write the rendering to <directory>/<id>.md and return that path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source.id}.md"
    path.write_text(to_markdown(source), encoding="utf-8")
    return path


def read_markdown(path: Path) -> Source:
    """Read a rendering written by `write_markdown` back into the Source it came from."""
    text = path.read_text(encoding="utf-8")
    front_matter = _FRONT_MATTER.match(text)
    if front_matter is None:
        raise ValueError(f"{path} does not start with ingest front matter")
    header = _header(front_matter.group(1))
    if "id" not in header:
        raise ValueError(f"{path} declares no source id")
    segments = _segments(text[front_matter.end() :])
    if not segments:
        raise ValueError(f"{path} has no segment markers")
    # Segment text is stored byte for byte so that span offsets survive the rendering, which
    # leaves a segment whose own text holds a marker line to split in two here. Counting the
    # segments against the header makes that an error rather than a source with moved offsets.
    declared = header.get("segments")
    if declared is not None and declared != str(len(segments)):
        raise ValueError(f"{path} declares {declared} segments but carries {len(segments)} markers")
    source = Source(id=header["id"], origin=header.get("origin") or str(path), segments=segments)
    # Spans stored earlier index the text layer this rendering was written from. An
    # edit to the file moves those offsets without touching the id, so the hash of
    # the text layer is what decides whether the source is still the same one.
    declared_hash = header.get("text_hash")
    if declared_hash is not None and declared_hash != source.text_hash:
        raise ValueError(f"{path} has been edited since ingest: its text layer no longer matches")
    return source


def _header(block: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            header[key.strip()] = _scalar(value.strip())
    return header


def _scalar(value: str) -> str:
    """Undo the double quoting that the rendering applies to ids and paths."""
    return json.loads(value) if value.startswith('"') else value


def _segments(body: str) -> tuple[Segment, ...]:
    markers = list(_MARKER.finditer(body))
    segments: list[Segment] = []
    for index, marker in enumerate(markers):
        last = index + 1 == len(markers)
        text = body[marker.end() : len(body) if last else markers[index + 1].start()]
        # Every block but the last carries the newline that joined it to the next one.
        if not last:
            text = text.removesuffix("\n")
        segments.append(Segment(number=int(marker.group(1)), text=text))
    return tuple(segments)

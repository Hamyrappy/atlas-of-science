"""The single client for every chat model the pipeline talks to.

Providers differ only by base URL and model name, so one class covers them all.
The disk cache is part of the contract rather than an optimisation: a run must be
repeatable, and a cached-only client replays a recorded run with no key and no network.

A reply carries what it cost and whether it was paid for, because a caller that cannot
see either has to invent the number it shows. `Reply.usage` is the provider's own count
for the call that produced the text and `Reply.tokens` adds it up; when `Reply.cached` is
true that call happened in an earlier run and nothing was spent now. `complete_json` hands
back the reply beside the object it parsed, for the same reason.

The environment, read by `ModelConfig.from_env` under a prefix (`ATLAS` by default):
`ATLAS_BASE_URL`, `ATLAS_MODEL`, `ATLAS_API_KEY`, and optionally `ATLAS_CACHE_DIR` and
`ATLAS_CACHED_ONLY`. The last one turns on replay: the key is then not required, which is
what lets a public demo run off a warmed cache with no key at all. The base URL and the
model stay required under replay, because both are part of the cache key.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from atlas.model import Frozen

DEFAULT_CACHE_DIR = Path(".atlas-cache")
MAX_ATTEMPTS = 3
BACKOFF_S = 1.0
TRUE = {"1", "true", "yes", "on"}


class LLMError(RuntimeError):
    """A model call failed."""


class CacheMiss(LLMError):
    """A cached-only client was asked for a reply it does not hold."""


class Reply(Frozen):
    """One model reply: the text, what the provider counted for it, and where it came from."""

    text: str
    usage: Mapping[str, int] = {}
    cached: bool = False

    @property
    def tokens(self) -> int:
        """The provider's count as one number: the total it sent, or the halves added up."""
        total = self.usage.get("total_tokens")
        if total is not None:
            return total
        return sum(self.usage.get(key, 0) for key in ("prompt_tokens", "completion_tokens"))


class ChatClient(Protocol):
    """What a step may assume of the client it is handed, and what a stub implements."""

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        """The reply to one prompt."""

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        """The reply to one prompt parsed as a single JSON object, and the reply it came from."""


@dataclass(frozen=True)
class ModelConfig:
    """Everything that distinguishes one model endpoint from another, plus how it is replayed."""

    base_url: str
    model: str
    api_key: str = ""
    temperature: float = 0.0
    timeout_s: float = 120.0
    cache_dir: Path = DEFAULT_CACHE_DIR
    cached_only: bool = False

    @classmethod
    def from_env(cls, prefix: str = "ATLAS") -> ModelConfig:
        """Read the endpoint out of the environment; under replay the key is not required."""

        def read(suffix: str) -> str:
            variable = f"{prefix}_{suffix}"
            value = os.environ.get(variable)
            if not value:
                raise LLMError(f"environment variable {variable} is not set")
            return value

        cached_only = os.environ.get(f"{prefix}_CACHED_ONLY", "").strip().lower() in TRUE
        cache_dir = os.environ.get(f"{prefix}_CACHE_DIR")
        return cls(
            base_url=read("BASE_URL"),
            model=read("MODEL"),
            api_key=os.environ.get(f"{prefix}_API_KEY", "") if cached_only else read("API_KEY"),
            cache_dir=Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR,
            cached_only=cached_only,
        )


class Client:
    """A chat-completions client with a disk cache in front of it."""

    def __init__(self, config: ModelConfig, cache_dir: Path | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else config.cache_dir
        # `transport` is the seam tests use to stand in for the network.
        self._http = httpx.Client(
            base_url=config.base_url, timeout=config.timeout_s,
            headers={"Authorization": f"Bearer {config.api_key}"}, transport=transport)

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        """Return the reply for one prompt, from the cache when it is there."""
        path = self.cache_dir / f"{self._cache_key(prompt, schema, system)}.json"
        if path.exists():
            recorded = json.loads(path.read_text(encoding="utf-8"))
            return Reply(text=recorded["reply"], usage=recorded.get("usage") or {}, cached=True)
        if self.config.cached_only:
            raise CacheMiss(f"cached-only client has no reply at {path}")
        text, usage = self._post(self._payload(prompt, schema, system))
        self._write_cache(path, text, usage)
        return Reply(text=text, usage=usage)

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        """Return the object one reply parses to and the reply, retrying once on bad JSON.

        The reply travels with the object because the caller that spends the tokens is
        the one that has to report them: parsing is not a reason to lose what it cost.
        """
        reply = self.complete(prompt, schema=schema, system=system)
        try:
            return parse_json_object(reply.text), reply
        except ValueError as error:
            repair = (f"{prompt}\n\nYour previous reply could not be parsed: {error}. "
                      "Reply with one JSON object and nothing else.")
        retried = self.complete(repair, schema=schema, system=system)
        try:
            return parse_json_object(retried.text), retried
        except ValueError as error:
            raise LLMError(f"model did not return JSON: {error}") from error

    def close(self) -> None:
        self._http.close()

    def _payload(self, prompt: str, schema: dict | None, system: str | None) -> dict:
        preamble = [{"role": "system", "content": system}] if system is not None else []
        payload: dict = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [*preamble, {"role": "user", "content": prompt}],
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "atlas", "strict": True, "schema": schema},
            }
        return payload

    def _post(self, payload: dict) -> tuple[str, dict[str, int]]:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._http.post("/chat/completions", json=payload)
            except httpx.HTTPError as error:
                # A refused connection or a timeout is a failed call like any other.
                raise LLMError(f"{self.config.base_url} could not be reached: {error}") from error
            if response.status_code == 200:
                body = response.json()
                # Providers nest their own extras under `usage`; only the counts are kept.
                counted = (body.get("usage") or {}).items()
                return body["choices"][0]["message"]["content"], {
                    key: value for key, value in counted if isinstance(value, int)
                }
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(BACKOFF_S * 2**attempt)
        raise LLMError(
            f"HTTP {response.status_code} from {self.config.model}: {response.text[:200]}")

    def _cache_key(self, prompt: str, schema: dict | None, system: str | None) -> str:
        config = self.config
        material = json.dumps([config.base_url, config.model, config.temperature, system,
                               prompt, schema], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _write_cache(self, path: Path, reply: str, usage: Mapping[str, int]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # A crash mid-write must not leave a truncated file that a later run reads as a reply,
        # which a cache hit would then serve forever without ever calling out again.
        temporary = path.with_suffix(".part")
        recorded = json.dumps({"reply": reply, "usage": dict(usage)}, ensure_ascii=False)
        temporary.write_text(recorded, encoding="utf-8")
        temporary.replace(path)


def parse_json_object(text: str) -> dict:
    """Parse the outermost JSON object in a reply, ignoring fences and prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply contains no JSON object")
    return json.loads(text[start : end + 1])

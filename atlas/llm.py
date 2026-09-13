"""The single client for every chat model the pipeline talks to.

Providers differ only by base URL and model name, so one class covers them all.
The disk cache is part of the contract rather than an optimisation: a run must be
repeatable, and `cached_only` replays a recorded one with no key and no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_CACHE_DIR = Path(".atlas-cache")
MAX_ATTEMPTS = 3
BACKOFF_S = 1.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """A model call failed."""


class CacheMiss(LLMError):
    """A cached-only client was asked for a reply it does not hold."""


@dataclass(frozen=True)
class ModelConfig:
    """Everything that distinguishes one model endpoint from another."""

    base_url: str
    model: str
    api_key: str
    temperature: float = 0.0
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls, prefix: str = "ATLAS") -> ModelConfig:
        def read(suffix: str) -> str:
            variable = f"{prefix}_{suffix}"
            value = os.environ.get(variable)
            if not value:
                raise LLMError(f"environment variable {variable} is not set")
            return value

        return cls(base_url=read("BASE_URL"), model=read("MODEL"), api_key=read("API_KEY"))


class Client:
    """A chat-completions client with a disk cache in front of it."""

    def __init__(self, config: ModelConfig, cache_dir: Path | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.cached_only = False
        # `transport` is the seam tests use to stand in for the network.
        self._http = httpx.Client(
            base_url=config.base_url.rstrip("/"), timeout=config.timeout_s,
            headers={"Authorization": f"Bearer {config.api_key}"}, transport=transport)

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> str:
        """Return the reply text for one prompt, from the cache when it is there."""
        key = self._cache_key(prompt, schema, system)
        cached = self._read_cache(key)
        if cached is not None:
            return cached
        if self.cached_only:
            raise CacheMiss(f"cached-only client has no reply for key {key}")
        reply = self._post(self._payload(prompt, schema, system))
        self._write_cache(key, reply)
        return reply

    def complete_json(self, prompt: str, schema: dict, *, system: str | None = None) -> dict:
        """Return the reply parsed as one JSON object, retrying once if it does not parse."""
        reply = self.complete(prompt, schema=schema, system=system)
        try:
            return parse_json_object(reply)
        except ValueError as error:
            repair = (f"{prompt}\n\nYour previous reply could not be parsed: {error}. "
                      "Reply with one JSON object and nothing else.")
        retried = self.complete(repair, schema=schema, system=system)
        try:
            return parse_json_object(retried)
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

    def _post(self, payload: dict) -> str:
        for attempt in range(MAX_ATTEMPTS):
            response = self._http.post("/chat/completions", json=payload)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(BACKOFF_S * 2**attempt)
        raise LLMError(
            f"HTTP {response.status_code} from {self.config.model}: {response.text[:200]}")

    def _cache_key(self, prompt: str, schema: dict | None, system: str | None) -> str:
        config = self.config
        material = json.dumps([config.base_url, config.model, config.temperature, system,
                               prompt, schema], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _read_cache(self, key: str) -> str | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["reply"]

    def _write_cache(self, key: str, reply: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        # A crash mid-write must not leave a truncated file that a later run reads as a reply.
        temporary = path.with_suffix(".part")
        temporary.write_text(json.dumps({"reply": reply}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def parse_json_object(text: str) -> dict:
    """Parse the outermost JSON object in a reply, ignoring fences and prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply contains no JSON object")
    return json.loads(text[start : end + 1])

"""Tests for the model client, served entirely by a fake transport."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from atlas import llm
from atlas.llm import CacheMiss, Client, LLMError, ModelConfig, Reply

CONFIG = ModelConfig(base_url="https://example.test/v1", model="test-model", api_key="k")
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def reply(text: str, **usage: int) -> dict:
    body = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    return body | {"usage": usage} if usage else body


def make_client(tmp_path: Path, *responses: httpx.Response) -> tuple[Client, list[httpx.Request]]:
    """A client answering from `responses` in order, repeating the last, recording requests."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    client = Client(CONFIG, cache_dir=tmp_path / "cache", transport=httpx.MockTransport(handle))
    return client, seen


def test_a_repeated_call_is_served_from_the_disk_cache(tmp_path: Path) -> None:
    client, seen = make_client(tmp_path, httpx.Response(200, json=reply("hello")))
    assert client.complete("question").text == "hello"
    assert client.complete("question").text == "hello"
    assert len(seen) == 1
    fresh, calls = make_client(tmp_path, httpx.Response(500, text="must not be called"))
    assert fresh.complete("question").text == "hello"
    assert calls == []


def test_a_reply_carries_what_the_provider_counted_and_whether_it_was_paid_for(
    tmp_path: Path,
) -> None:
    client, _ = make_client(
        tmp_path, httpx.Response(200, json=reply("hello", prompt_tokens=11, completion_tokens=2))
    )

    first = client.complete("question")
    again = client.complete("question")

    assert (first.usage, first.cached) == ({"prompt_tokens": 11, "completion_tokens": 2}, False)
    assert (again.usage, again.cached) == (first.usage, True)


def test_a_provider_extra_under_usage_that_is_not_a_count_is_dropped(tmp_path: Path) -> None:
    body = reply("hello", prompt_tokens=3)
    body["usage"]["prompt_tokens_details"] = {"cached_tokens": 1}

    client, _ = make_client(tmp_path, httpx.Response(200, json=body))

    assert client.complete("question").usage == {"prompt_tokens": 3}


def test_the_cache_directory_defaults_to_dot_atlas_cache() -> None:
    client = Client(CONFIG)
    assert client.cache_dir == Path(".atlas-cache")
    client.close()


def test_the_cache_directory_of_the_configuration_is_the_one_the_client_uses(
    tmp_path: Path,
) -> None:
    client = Client(replace(CONFIG, cache_dir=tmp_path / "replies"))
    assert client.cache_dir == tmp_path / "replies"
    client.close()


def test_a_different_system_prompt_is_a_different_cache_entry(tmp_path: Path) -> None:
    client, seen = make_client(tmp_path, httpx.Response(200, json=reply("hello")))
    client.complete("question")
    client.complete("question", system="be brief")
    assert len(seen) == 2


def test_cached_only_raises_on_a_miss(tmp_path: Path) -> None:
    client, seen = make_client(tmp_path, httpx.Response(200, json=reply("hello")))
    client.complete("question")
    replay = Client(replace(CONFIG, cached_only=True), cache_dir=tmp_path / "cache")

    assert replay.complete("question").text == "hello"
    with pytest.raises(CacheMiss):
        replay.complete("another question")
    assert len(seen) == 1


def test_rate_limit_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    client, seen = make_client(
        tmp_path, httpx.Response(429, text="slow down"), httpx.Response(200, json=reply("hello"))
    )
    assert client.complete("question").text == "hello"
    assert len(seen) == 2


def test_server_error_exhausts_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    client, seen = make_client(tmp_path, httpx.Response(529, text="overloaded"))
    with pytest.raises(LLMError, match="529"):
        client.complete("question")
    assert len(seen) == llm.MAX_ATTEMPTS


def test_client_error_raises_immediately_with_status_and_body(tmp_path: Path) -> None:
    body = "bad request: " + "x" * 500
    client, seen = make_client(tmp_path, httpx.Response(400, text=body))
    with pytest.raises(LLMError) as error:
        client.complete("question")
    assert "400" in str(error.value)
    assert str(error.value).endswith(body[:200])
    assert len(seen) == 1


def test_an_unreachable_endpoint_raises_llm_error(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = Client(CONFIG, cache_dir=tmp_path, transport=httpx.MockTransport(refuse))
    with pytest.raises(LLMError, match="could not be reached"):
        client.complete("question")


def test_schema_requests_strict_structured_output(tmp_path: Path) -> None:
    client, seen = make_client(tmp_path, httpx.Response(200, json=reply('{"answer": "yes"}')))
    client.complete("question", schema=SCHEMA, system="be brief")
    payload = json.loads(seen[0].content)
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "atlas", "strict": True, "schema": SCHEMA},
    }
    assert payload["messages"][0] == {"role": "system", "content": "be brief"}
    assert payload["model"] == CONFIG.model


def test_complete_json_parses_a_fenced_reply(tmp_path: Path) -> None:
    fenced = 'Here it is:\n```json\n{"answer": "yes"}\n```\n'
    client, _ = make_client(tmp_path, httpx.Response(200, json=reply(fenced, total_tokens=7)))
    body, answered = client.complete_json("question", SCHEMA)
    assert body == {"answer": "yes"}
    # The caller that spends the tokens is the one that reports them, so parsing keeps the reply.
    assert (answered.tokens, answered.cached) == (7, False)


def test_complete_json_retries_once_on_malformed_json(tmp_path: Path) -> None:
    client, seen = make_client(
        tmp_path,
        httpx.Response(200, json=reply("{not json at all")),
        httpx.Response(200, json=reply('{"answer": "yes"}')),
    )
    assert client.complete_json("question", SCHEMA)[0] == {"answer": "yes"}
    assert len(seen) == 2
    assert "question" in json.loads(seen[1].content)["messages"][0]["content"]


def test_complete_json_gives_up_after_one_retry(tmp_path: Path) -> None:
    client, seen = make_client(tmp_path, httpx.Response(200, json=reply("no object here")))
    with pytest.raises(LLMError, match="did not return JSON"):
        client.complete_json("question", SCHEMA)
    assert len(seen) == 2


def test_from_env_reads_the_prefixed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for suffix, value in (("BASE_URL", "u"), ("MODEL", "m"), ("API_KEY", "k")):
        monkeypatch.setenv(f"OTHER_{suffix}", value)
    config = ModelConfig.from_env("OTHER")
    assert (config.base_url, config.model, config.api_key) == ("u", "m", "k")


def test_from_env_error_names_the_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_BASE_URL", "https://example.test/v1")
    monkeypatch.delenv("ATLAS_MODEL", raising=False)
    with pytest.raises(LLMError, match="ATLAS_MODEL"):
        ModelConfig.from_env()


def test_replay_from_the_environment_needs_no_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for suffix, value in (("BASE_URL", "u"), ("MODEL", "m"), ("CACHED_ONLY", "yes")):
        monkeypatch.setenv(f"ATLAS_{suffix}", value)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("ATLAS_API_KEY", raising=False)

    config = ModelConfig.from_env()

    assert (config.cached_only, config.api_key, config.cache_dir) == (True, "", tmp_path)


def test_a_key_is_still_required_when_replay_is_not_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for suffix, value in (("BASE_URL", "u"), ("MODEL", "m"), ("CACHED_ONLY", "no")):
        monkeypatch.setenv(f"ATLAS_{suffix}", value)
    monkeypatch.delenv("ATLAS_API_KEY", raising=False)

    with pytest.raises(LLMError, match="ATLAS_API_KEY"):
        ModelConfig.from_env()


def test_a_reply_totals_the_counts_a_provider_sends_under_whatever_name() -> None:
    assert Reply(text="", usage={"total_tokens": 12}).tokens == 12
    assert Reply(text="", usage={"prompt_tokens": 8, "completion_tokens": 4}).tokens == 12
    assert Reply(text="").tokens == 0

"""Unit tests for AnthropicLLMClient's error handling -- all offline, no
network. A fake anthropic_client is injected so these exercise the exact
except-clause mapping in llm.py without needing real credentials or a
live API call."""
import types

import httpx2
import pytest

from apidrift.llm import AnthropicLLMClient, LLMCallError, TruncatedResponseError

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _sdk_error(cls, message, status_code=400):
    req = httpx2.Request("POST", "http://test")
    resp = httpx2.Response(status_code, request=req)
    return cls(message, response=resp, body=None)


class _FakeMessages:
    def __init__(self, raises=None, response=None):
        self._raises = raises
        self._response = response

    def create(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeAnthropicClient:
    def __init__(self, raises=None, response=None):
        self.messages = _FakeMessages(raises, response)


def _client(raises=None, response=None):
    return AnthropicLLMClient(anthropic_client=_FakeAnthropicClient(raises, response))


def _fake_response(stop_reason="end_turn", text='{"ok": true}'):
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=5,
                                   cache_creation_input_tokens=0, cache_read_input_tokens=0)
    content = [types.SimpleNamespace(type="text", text=text)]
    return types.SimpleNamespace(stop_reason=stop_reason, usage=usage, content=content)


@pytest.mark.parametrize("exc_cls,status,snippet", [
    (__import__("anthropic").AuthenticationError, 401, "authentication failed"),
    (__import__("anthropic").PermissionDeniedError, 403, "lacks permission"),
    (__import__("anthropic").RateLimitError, 429, "rate limited"),
    (__import__("anthropic").NotFoundError, 404, "not found"),
    (__import__("anthropic").BadRequestError, 400, "rejected the request"),
])
def test_sdk_errors_become_plain_language_llm_call_error(exc_cls, status, snippet):
    client = _client(raises=_sdk_error(exc_cls, "boom", status_code=status))
    with pytest.raises(LLMCallError, match=snippet):
        client.complete("some_stage", "sys", "user", SCHEMA)


def test_credit_exhaustion_style_bad_request_is_plain_language():
    client = _client(raises=_sdk_error(
        __import__("anthropic").BadRequestError, "Your credit balance is too low", status_code=400
    ))
    with pytest.raises(LLMCallError, match="out of API credits"):
        client.complete("adjudicate_chunk_000", "sys", "user", SCHEMA)


def test_truncated_response_is_not_reported_as_bad_json():
    client = _client(response=_fake_response(stop_reason="max_tokens", text='{"patterns": [{"na'))
    with pytest.raises(TruncatedResponseError, match="not malformed JSON"):
        client.complete("vocabulary", "sys", "user", SCHEMA, max_tokens=8000)


def test_truncated_response_still_counts_usage():
    client = _client(response=_fake_response(stop_reason="max_tokens", text='{"patterns": [{"na'))
    with pytest.raises(TruncatedResponseError):
        client.complete("vocabulary", "sys", "user", SCHEMA, max_tokens=8000)
    assert client.usage_totals["output_tokens"] == 5
    assert len(client.calls) == 1


def test_normal_completion_still_works():
    client = _client(response=_fake_response(stop_reason="end_turn", text='{"ok": true}'))
    result = client.complete("factblock", "sys", "user", SCHEMA)
    assert result == {"ok": True}

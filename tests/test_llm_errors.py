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


class _FakeStreamContext:
    """Stands in for the real MessageStreamManager: entering the `with`
    block is where a connection-time error (auth, rate limit, bad
    request...) surfaces in the real SDK, and get_final_message() is where
    a mid-stream failure (the connection dropping partway through reading
    the body) surfaces instead -- these are two different points in real
    usage, so the fake keeps them distinct rather than raising everything
    from one place."""

    def __init__(self, response=None, raises_on_enter=None, raises_on_final=None):
        self._response = response
        self._raises_on_enter = raises_on_enter
        self._raises_on_final = raises_on_final

    def __enter__(self):
        if self._raises_on_enter is not None:
            raise self._raises_on_enter
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        if self._raises_on_final is not None:
            raise self._raises_on_final
        return self._response


class _FakeMessages:
    def __init__(self, raises=None, response=None, raises_mid_stream=None):
        self._raises = raises
        self._response = response
        self._raises_mid_stream = raises_mid_stream

    def stream(self, **kwargs):
        return _FakeStreamContext(
            response=self._response,
            raises_on_enter=self._raises,
            raises_on_final=self._raises_mid_stream,
        )


class _FakeAnthropicClient:
    def __init__(self, raises=None, response=None, raises_mid_stream=None):
        self.messages = _FakeMessages(raises, response, raises_mid_stream)


def _client(raises=None, response=None, raises_mid_stream=None):
    return AnthropicLLMClient(
        anthropic_client=_FakeAnthropicClient(raises, response, raises_mid_stream)
    )


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


@pytest.mark.parametrize("exc", [
    httpx2.ReadError("connection dropped mid-read"),
    httpx2.RemoteProtocolError("peer closed connection without complete response"),
])
def test_mid_stream_network_failure_becomes_plain_language_llm_call_error(exc):
    """A new error path streaming introduces: the connection can drop after
    it's already open and tokens have been billed, distinct from a
    connection-establishment failure (covered by the parametrized SDK-error
    cases above) -- this must still surface as a clean LLMCallError, not a
    raw httpx2 traceback."""
    client = _client(raises_mid_stream=exc)
    with pytest.raises(LLMCallError, match="interrupted while streaming"):
        client.complete("some_stage", "sys", "user", SCHEMA)

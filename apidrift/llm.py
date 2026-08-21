"""LLM call layer. One interface (`LLMClient.complete`), three
implementations, so the exact same pipeline code runs against the real
API, a recording wrapper, or a recorded replay -- only `cli.py` ever
constructs the real one.
"""
import hashlib
import json
import os


class ReplayMiss(Exception):
    """Raised when a replay cassette has no recorded response for a
    request the pipeline actually made. This is a deliberate loud
    failure, not a fallback: it means the pipeline asked a different
    question than the cassette was recorded against (a real plumbing
    change), and that must not be silently papered over with an
    unrelated recorded answer."""


class LLMError(Exception):
    """Base for errors AnthropicLLMClient raises when a call can't be
    trusted. str(e) is a plain-language line naming the stage -- callers
    print it and stop, never a raw SDK traceback."""


class LLMCallError(LLMError):
    """The request itself failed: auth, permissions, rate limit, a
    rejected request (including an out-of-credits account), a server
    error, or a network failure."""


class TruncatedResponseError(LLMError):
    """The model's response was cut off by the max_tokens ceiling before
    it finished. This is an incomplete response, not malformed JSON --
    raising max_tokens (or asking for less in one call) is the fix, not
    retrying the same call or treating it as a parse error."""


# $/1M tokens, Anthropic API, cached 2026-06-24. Keyed by model name so a
# run against a model this table doesn't know about degrades to reporting
# raw token counts rather than a wrong dollar figure.
PRICE_PER_MTOK = {
    "claude-opus-5": {
        "input_tokens": 5.00,
        "output_tokens": 25.00,
        "cache_creation_input_tokens": 6.25,
        "cache_read_input_tokens": 0.50,
    },
}


def estimate_cost(usage_totals, model):
    """Returns a dollar estimate, or None if `model` has no entry in
    PRICE_PER_MTOK -- callers must handle that by reporting token counts
    without a cost figure, not by guessing with a different model's price."""
    prices = PRICE_PER_MTOK.get(model)
    if prices is None:
        return None
    return sum(usage_totals[k] / 1_000_000 * prices[k] for k in prices)


def format_usage_report(client, model):
    """One human-readable block covering every call `client` made so far
    (partial usage on a failed/guard-stopped run included, since those
    calls were still billed) -- the same shape cli.py and the acceptance
    tests print, so a run's cost is never invisible."""
    totals = client.usage_totals
    total_tokens = sum(totals.values())
    lines = [
        f"token usage: input={totals['input_tokens']} output={totals['output_tokens']} "
        f"cache_write={totals['cache_creation_input_tokens']} cache_read={totals['cache_read_input_tokens']}",
    ]
    cost = estimate_cost(totals, model)
    if cost is not None:
        lines.append(f"total tokens: {total_tokens}  estimated cost: ${cost:.4f}  "
                      f"({len(client.calls)} API calls)")
    else:
        lines.append(f"total tokens: {total_tokens}  ({len(client.calls)} API calls)  "
                      f"-- no pricing data for model {model!r}, cost not estimated")
    return "\n".join(lines)


def _request_key(system_text, user_text):
    h = hashlib.sha256()
    h.update(system_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_text.encode("utf-8"))
    return h.hexdigest()[:24]


class LLMClient:
    """Interface. `complete` returns a parsed JSON dict matching `schema`
    (schema is advisory for the real client -- it's what gets sent as
    output_config.format -- and load-bearing for the fake clients, which
    don't validate against it themselves; callers validate the returned
    dict against their own hard-fail contract, same as every other stage
    in this pipeline)."""

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        raise NotImplementedError


class AnthropicLLMClient(LLMClient):
    """The only implementation that hits the network. Constructed only in
    cli.py."""

    def __init__(self, model="claude-opus-5", anthropic_client=None):
        import anthropic
        self.model = model
        self.client = anthropic_client or anthropic.Anthropic()
        self.usage_totals = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }
        self.calls = []

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        import anthropic

        system = system_text
        if cache_system:
            system = [{"type": "text", "text": system_text,
                       "cache_control": {"type": "ephemeral"}}]
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": user_text}],
            )
        except anthropic.AuthenticationError as e:
            raise LLMCallError(
                f"[{stage}] authentication failed -- check that ANTHROPIC_API_KEY (or "
                f"another credential source) is set and valid: {e.message}"
            ) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMCallError(
                f"[{stage}] the API key lacks permission for this request: {e.message}"
            ) from e
        except anthropic.RateLimitError as e:
            raise LLMCallError(
                f"[{stage}] rate limited by the Anthropic API -- wait and retry: {e.message}"
            ) from e
        except anthropic.NotFoundError as e:
            raise LLMCallError(
                f"[{stage}] the Anthropic API returned 'not found' -- check the --model name: {e.message}"
            ) from e
        except anthropic.BadRequestError as e:
            raise LLMCallError(
                f"[{stage}] the Anthropic API rejected the request: {e.message} "
                f"(an account out of API credits shows up as this kind of error)"
            ) from e
        except anthropic.APIStatusError as e:
            raise LLMCallError(
                f"[{stage}] Anthropic API error (status {e.status_code}): {e.message}"
            ) from e
        except anthropic.APIConnectionError as e:
            raise LLMCallError(f"[{stage}] network error reaching the Anthropic API: {e}") from e

        usage = getattr(response, "usage", None)
        call_usage = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        }
        for k, v in call_usage.items():
            self.usage_totals[k] += v
        self.calls.append({"stage": stage, "usage": call_usage})

        if response.stop_reason == "max_tokens":
            raise TruncatedResponseError(
                f"[{stage}] the model's response was cut off at the {max_tokens}-token "
                f"max_tokens limit before it finished -- this is an incomplete response, "
                f"not malformed JSON. Raise max_tokens for this stage (or reduce what it's "
                f"asked to produce in one call); retrying the same call will hit the same wall."
            )

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ValueError(f"[{stage}] model response had no text block "
                              f"(stop_reason={response.stop_reason})")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"[{stage}] model response was not valid JSON: {e}\n"
                              f"raw text: {text[:2000]}")


class RecordingLLMClient(LLMClient):
    """Wraps a real client. Every call is recorded to `cassette_path`,
    keyed by a hash of (system, user) so a replay can look the exact
    request up later without depending on call order. Written after every
    call, not just at the end, so a crash partway through a run still
    leaves a usable partial cassette."""

    def __init__(self, inner, cassette_path):
        self.inner = inner
        self.cassette_path = cassette_path
        self._cassette = {}
        if os.path.isfile(cassette_path):
            with open(cassette_path) as f:
                self._cassette = json.load(f)

    @property
    def usage_totals(self):
        return self.inner.usage_totals

    @property
    def calls(self):
        return self.inner.calls

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        result = self.inner.complete(stage, system_text, user_text, schema,
                                      cache_system=cache_system, max_tokens=max_tokens,
                                      effort=effort)
        key = _request_key(system_text, user_text)
        self._cassette[key] = {
            "stage": stage,
            "system_excerpt": system_text[:200],
            "user_excerpt": user_text[:200],
            "response": result,
        }
        os.makedirs(os.path.dirname(self.cassette_path) or ".", exist_ok=True)
        tmp = self.cassette_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._cassette, f, indent=2)
        os.replace(tmp, self.cassette_path)
        return result


class ReplayLLMClient(LLMClient):
    """Fake client for the offline replay test. Never touches the
    network. Raises ReplayMiss -- loudly, not silently -- if the pipeline
    asks something the cassette doesn't have."""

    def __init__(self, cassette_path):
        with open(cassette_path) as f:
            self._cassette = json.load(f)

    def complete(self, stage, system_text, user_text, schema, cache_system=False,
                 max_tokens=8000, effort="high"):
        key = _request_key(system_text, user_text)
        entry = self._cassette.get(key)
        if entry is None:
            raise ReplayMiss(
                f"[{stage}] no cassette entry for this request -- the pipeline asked "
                f"something the cassette wasn't recorded against (re-record with "
                f"APIDRIFT_RECORD_CASSETTE set on the acceptance test if this is "
                f"an intentional change).\n"
                f"system[:200]={system_text[:200]!r}\nuser[:200]={user_text[:200]!r}"
            )
        return json.loads(json.dumps(entry["response"]))  # defensive deep copy

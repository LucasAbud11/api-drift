"""Property-based tests for guards._pattern_tokens' regex-escape handling.

This is the third bug found in this function (lowercasing mismatch,
then substring containment, now escape fusion) -- all three made
coverage look worse than reality, none of them was caught by example
tests alone because each was invisible until a pattern happened to be
shaped a particular way. Property tests instead assert invariants that
must hold for ANY regex shape, so a fourth bug in the same family has
a much narrower place to hide.

No third-party dependency: this hand-rolls the generate-many-random-
cases-and-check-an-invariant idea directly in stdlib `random`, seeded
for reproducibility, rather than reaching for `hypothesis` (not a
project dependency today). `_TRIALS` random regexes are built per
property from a fixed grammar of realistic regex syntax (anchors,
escapes, alternation, groups, quantifiers, character classes) wrapped
around known identifiers, so a failure prints a concrete, reproducible
regex string.
"""
import random
import re

from apidrift import guards

_SEED = 20260826
_TRIALS = 500

# Identifiers with a variety of shapes: plain word, mixed case, leading
# uppercase run (the exact shape that triggered the original bug --
# `MCPError`/`McpError` are indistinguishable from the escape's own
# fused "b" once corrupted), underscored, single letters that collide
# with escape-class letters themselves (b, d, w, s, n, r, t, A, Z) to
# make sure a real identifier named e.g. `s` isn't confused with `\s`.
_IDENTIFIERS = [
    "Foo", "foo", "McpError", "MCPError", "ClientSession",
    "client_tracking_info", "http_client", "FastMCP", "widget2",
    "X1Y2Z3", "ab", "Zz", "Bb", "Dd", "Ww", "Ss",
]

# Every filler is chosen to carry ZERO literal alphanumeric content of
# its own (only backslash-escapes, anchoring punctuation, or a
# self-contained character class) -- so the expected token set from a
# generated regex is always exactly the identifiers embedded in it,
# nothing more, nothing less, and any deviation is a real bug rather
# than a fixture artifact. Grouping punctuation ("(", "(?:", ")") is
# deliberately NOT in this list -- it's added as matched pairs in
# _random_regex_and_expected instead, so the generator can never itself
# produce an unbalanced (invalid) regex.
_ZERO_CONTENT_FILLERS = [
    "", r"\b", r"\B", r"\A", r"\Z", "^", "$",
    r"\s*", r"\s+", r"\s?", r"\d*", r"\d+", r"\w*", r"\W+", r"\S*", r"\D+",
    r"[^)]*", r"[^\s]*",
    r"\n", r"\t", r"\r",
    # \1/\12-style backreferences are deliberately excluded from this
    # generator: a backreference to a group that doesn't exist is itself
    # an invalid regex (unlike every other filler here), so it can't be
    # combined freely without breaking test_property_generated_regexes_
    # stay_close_to_realistic_syntax's re.compile() check. Backreference
    # stripping is covered directly instead, in
    # test_property_escape_class_letters_alone_never_become_tokens.
]


def _normalize(identifier):
    return identifier.lower().replace("_", "")


def _random_regex_and_expected(rng, n_identifiers):
    chosen = [rng.choice(_IDENTIFIERS) for _ in range(n_identifiers)]
    parts = []
    for ident in chosen:
        prefix = rng.choice(_ZERO_CONTENT_FILLERS)
        suffix = rng.choice(_ZERO_CONTENT_FILLERS)
        atom = f"{prefix}{ident}{suffix}"
        # Grouping (and any quantifier, which can only ever legally
        # follow a complete atom/group) is applied as a matched pair in
        # the same step, so the result is always a valid regex.
        if rng.random() < 0.4:
            atom = f"(?:{atom})"
            if rng.random() < 0.3:
                atom += rng.choice(["*", "+", "?", "{1,3}", "{2}"])
        elif rng.random() < 0.2:
            atom = f"({atom})"
        parts.append(atom)
    body = "|".join(parts)
    if rng.random() < 0.5:
        body = f"(?:{body})"
        if rng.random() < 0.5:
            body += rng.choice(["*", "+", "?", "{1,3}", "{2}"])
    expected = {_normalize(ident) for ident in chosen}
    return body, expected, chosen


def test_property_identifier_always_survives_any_surrounding_regex_syntax():
    """A pattern whose regex contains an identifier must always yield
    that identifier as a token, for any surrounding regex syntax
    (anchors, escapes, alternation, groups, quantifiers, character
    classes) -- checked as exact set equality, not just "is present",
    so a spurious EXTRA token (a leaked escape letter) fails it too."""
    rng = random.Random(_SEED)
    for trial in range(_TRIALS):
        n = rng.choice([1, 1, 1, 2, 2, 3])
        regex, expected, chosen = _random_regex_and_expected(rng, n)
        actual = guards._pattern_tokens(regex)
        assert actual == expected, (
            f"trial {trial}: regex={regex!r} identifiers={chosen!r} "
            f"expected={expected!r} actual={actual!r}"
        )


def test_property_tokenization_is_invariant_to_b_anchoring():
    """tokens(r'\\bFoo\\b') == tokens('Foo') -- \\b is a zero-width
    assertion; wrapping an identifier in it must never change, add to,
    or corrupt the identifier's own token."""
    rng = random.Random(_SEED + 1)
    for trial in range(_TRIALS):
        ident = rng.choice(_IDENTIFIERS)
        bare = guards._pattern_tokens(ident)
        anchored_both = guards._pattern_tokens(f"\\b{ident}\\b")
        anchored_left = guards._pattern_tokens(f"\\b{ident}")
        anchored_right = guards._pattern_tokens(f"{ident}\\b")
        assert bare == anchored_both == anchored_left == anchored_right, (
            f"trial {trial}: ident={ident!r} bare={bare!r} "
            f"both={anchored_both!r} left={anchored_left!r} right={anchored_right!r}"
        )


def test_property_no_token_contains_a_character_from_regex_syntax():
    """No token in the result may contain a character that came from
    regex syntax rather than from the pattern's own literal text: every
    token must be a substring of the concatenation of the (normalized)
    identifiers actually embedded in the regex -- if any regex-syntax
    character (an escape's own letter, a quantifier digit, a group
    marker) leaked into a token, it would not satisfy this."""
    rng = random.Random(_SEED + 2)
    for trial in range(_TRIALS):
        n = rng.choice([1, 1, 2, 2, 3])
        regex, expected, chosen = _random_regex_and_expected(rng, n)
        actual = guards._pattern_tokens(regex)
        pool = "".join(sorted(expected))
        for token in actual:
            assert token in expected, (
                f"trial {trial}: regex={regex!r} produced token {token!r} not in "
                f"the identifiers actually embedded {expected!r} (pool={pool!r})"
            )


def test_property_escape_class_letters_alone_never_become_tokens():
    """A bare escape sequence with no adjacent identifier text (`\\b`,
    `\\d+`, `\\s*`, a backreference) must contribute nothing -- not even
    its own escaped letter -- to the token set."""
    rng = random.Random(_SEED + 3)
    escape_only_regexes = [
        r"\b", r"\B", r"\A", r"\Z", r"\d+", r"\D+", r"\w*", r"\W*",
        r"\s+", r"\S+", r"\n", r"\t", r"\r", r"\1", r"\12",
        r"\b\s*\d+\b", r"(?:\b\B)+", r"\A\Z",
    ]
    for regex in escape_only_regexes:
        assert guards._pattern_tokens(regex) == set(), (
            f"regex={regex!r} should contribute zero tokens, got {guards._pattern_tokens(regex)!r}"
        )


def test_property_generated_regexes_stay_close_to_realistic_syntax():
    """Sanity check on the generator itself: every produced regex must
    still be a syntactically valid Python regex (mirrors the constraint
    validate_vocabulary already enforces on every real pattern), so
    these properties are exercised against the same shape of input the
    guard actually receives in production, not an unrealistic fixture."""
    rng = random.Random(_SEED + 4)
    for _ in range(_TRIALS):
        n = rng.choice([1, 2, 3])
        regex, _expected, _chosen = _random_regex_and_expected(rng, n)
        re.compile(regex)  # raises re.error if the generator ever produces garbage

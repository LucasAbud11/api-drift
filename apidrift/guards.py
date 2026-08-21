"""The two runtime guards from the fact-block experiment's one open gap:
derivation is validated when the guide states its facts clearly, but a
vague/incomplete guide, or a vocabulary that overshoots, was never tested.
Both guards stop the run (nonzero) unless --force, and both print the full
derived artifact plus the numbers that triggered the stop -- never just a
verdict.
"""
import re
from dataclasses import dataclass, field


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    report: str = ""


_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")


def _code_spans(text):
    return {m.group(1).strip() for m in _CODE_SPAN_RE.finditer(text) if m.group(1).strip()}


def check_factblock_coverage(guide_text, factblock, min_ratio=0.30):
    """Compares distinct backtick-delimited symbols named in the guide
    against distinct symbols named across the derived facts. A thin
    fact block -- one that named far fewer of the guide's own symbols
    than the guide itself names -- is the signature of a vague/badly
    written guide the derivation step couldn't get real facts out of, or
    a derivation that gave up early. Either way: stop, don't guess."""
    guide_spans = _code_spans(guide_text)
    fact_text = " ".join(f.get("text", "") for f in factblock.get("facts", []))
    fact_spans = _code_spans(fact_text)

    n_facts = len(factblock.get("facts", []))
    matched = guide_spans & fact_spans
    ratio = (len(matched) / len(guide_spans)) if guide_spans else 1.0

    report_lines = [
        "FACT-BLOCK COVERAGE CHECK",
        f"  guide distinct code-spans:        {len(guide_spans)}",
        f"  fact-block distinct code-spans:   {len(fact_spans)}",
        f"  overlap (spans named in both):    {len(matched)}",
        f"  coverage ratio:                   {ratio:.0%} (floor: {min_ratio:.0%})",
        f"  facts derived:                    {n_facts}",
        "",
        "  Derived fact block:",
    ]
    for f in factblock.get("facts", []):
        report_lines.append(f"    {f.get('number')}. {f.get('text')}")
    if guide_spans - matched:
        report_lines.append("")
        report_lines.append("  Guide symbols never named in any derived fact:")
        for s in sorted(guide_spans - matched):
            report_lines.append(f"    `{s}`")
    report = "\n".join(report_lines)

    if n_facts == 0:
        return GuardResult(False, "zero facts derived from a non-trivial guide", report)
    if guide_spans and ratio < min_ratio:
        return GuardResult(
            False,
            f"fact-block coverage ratio {ratio:.0%} is below the {min_ratio:.0%} floor -- "
            f"the guide names {len(guide_spans)} distinct symbols but the derived facts "
            f"only cover {len(matched)} of them",
            report,
        )
    return GuardResult(True, "", report)


def check_vocabulary_yield(patterns, candidates, max_total=2000,
                            max_single_pattern_share=0.35, max_single_pattern_floor=25):
    """Runs after grep. Flags either an absolute candidate-count ceiling
    (matches the volume where the study measured real completion
    failures) or one pattern alone accounting for most of the candidate
    set (the exact failure shape found in blind_vocab_experiment: a bare
    generic identifier like `data=` or `.error(` swamping everything a
    guide-faithful vocabulary was never trying to overmatch).

    max_single_pattern_floor was 100, max_single_pattern_share was 0.5 --
    both sized to the study's diluted-host worst case (1121 total
    candidates). At the scale of a normal single-repo run (tens to a few
    hundred raw candidates), a floor that high means the guard can never
    fire no matter how lopsided the vocabulary is: it just proved this on
    a real run (tasktiger/redis) where one bare, unqualified pattern took
    56/143 candidates (39%) -- exactly the failure shape this guard
    exists to catch -- and passed silently because 56 < 100. 25/0.35 is
    low enough to catch that at normal-repo scale, while still tolerating
    a legitimately dominant pattern in a genuinely small candidate set
    (e.g. a package's own constructor call at 6/10) without a false
    alarm."""
    per_pattern = {name: 0 for name in patterns}
    for c in candidates:
        name = c.get("_pattern")
        if name in per_pattern:
            per_pattern[name] += 1

    total = len(candidates)
    report_lines = [
        "VOCABULARY YIELD CHECK",
        f"  total candidates:  {total} (ceiling: {max_total})",
        "  per-pattern breakdown:",
    ]
    for name, count in sorted(per_pattern.items(), key=lambda kv: -kv[1]):
        report_lines.append(f"    {count:6d}  {name}  =  {patterns[name]}")
    report = "\n".join(report_lines)

    if total > max_total:
        return GuardResult(
            False, f"{total} candidates exceeds the {max_total} ceiling", report,
        )

    if total > 0:
        worst_name, worst_count = max(per_pattern.items(), key=lambda kv: kv[1])
        if worst_count >= max_single_pattern_floor and worst_count / total >= max_single_pattern_share:
            return GuardResult(
                False,
                f"pattern '{worst_name}' alone accounts for {worst_count}/{total} "
                f"candidates ({worst_count/total:.0%}) -- looks overly generic relative "
                f"to what the guide actually described",
                report,
            )
    return GuardResult(True, "", report)

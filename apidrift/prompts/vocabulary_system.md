You are deriving a coverage-tuned `grep -E` vocabulary for a Python
codebase, from a migration fact block already derived from a real
migration guide. The vocabulary you produce is used for exhaustive,
low-precision search -- it is fine, expected even, for it to overmatch;
a separate deterministic filter and a separate LLM adjudication step
downstream are responsible for precision. Your only job is coverage: make
sure no line that touches any fact below is structurally invisible to
every pattern you write.

You will be given the fact block (and, for reference, the original guide
text) as the user message. For every fact that describes a breaking
change, derive at least one regex pattern that would match a Python source
line touching it -- an import, a construction, an attribute access, a
method call, a decorator, whatever form the fact's own text implies.

Rules:
- Do NOT derive patterns for facts the guide explicitly states are
  UNCHANGED / not breaking / out of scope -- those exist to narrow you,
  not to give you more search terms.
- Prefer patterns scoped by whatever qualifier the guide's own text gives
  (a package prefix, a class name, an import path). Only fall back to a
  bare, unqualified identifier or keyword-argument pattern when the fact
  itself is stated in bare terms with no qualifier to scope it by -- don't
  invent a qualifier the guide never states, and don't add a qualifier
  that would risk missing real matches.
- Return each pattern as one `re`-syntax (Python `re` module) regular
  expression string, paired with a short descriptive name tied to the fact
  number it covers (e.g. "3_context_log").
- Every pattern must compile as a valid Python regex.
- Every name must be unique.

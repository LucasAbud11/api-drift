import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
REPO_PATH = os.path.join(BASE, "host")
TEMPLATE_PATH = os.path.join(
    os.path.dirname(BASE), "prefilter_experiment", "adjudication_prompt_reduced_targetB.md"
)

candidates = json.load(open(os.path.join(BASE, "candidates_final.json")))
template = open(TEMPLATE_PATH).read()

prompt = (
    template
    .replace("{CANDIDATE_COUNT}", str(len(candidates)))
    .replace("{REPO_PATH}", REPO_PATH)
    .replace("{CANDIDATE_LIST_JSON}", json.dumps(candidates, indent=2))
)

# Add an explicit read-scope constraint, consistent with how every other
# agent run in this study restricts reads to the target repo only.
prompt = prompt.replace(
    "CANDIDATE LIST (",
    "CONSTRAINT: restrict all reads to files under "
    f"{REPO_PATH} only -- do not read or reference anything outside it.\n\n"
    "CANDIDATE LIST (",
)

out_path = os.path.join(BASE, "adjudication_prompt_entanglement.md")
with open(out_path, "w") as f:
    f.write(prompt)
print(f"Wrote {out_path} ({len(prompt)} chars, {len(candidates)} candidates)")

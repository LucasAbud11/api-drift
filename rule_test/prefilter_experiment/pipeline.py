"""
Idempotent, chunked adjudication pipeline. This is the state machine half
of "grep -> prefilter -> agent adjudication" made resumable: it decides
what work remains and merges what's done, but it does not itself call an
LLM (that dispatch has to happen one level up, by whatever is driving
this -- a human, an orchestrator process, or an agent with tool access).

Design, and why it's shaped this way:

  - Work unit = one CHUNK of candidates (default chunk size below), not
    the whole run. A run at 1121 candidates in single-shot form failed
    2 of 3 times in this study; the empirical fix that actually worked
    was candidate-count reduction (1121 -> 111), not chunking -- but
    chunking is still the correct hedge for whatever candidate count a
    *future* target's vocabulary produces, since nothing guarantees the
    reduction stage will always get a host down to double digits.

  - State lives on disk as one file per chunk, written only once that
    chunk's output has been validated. Resuming a run means: look at
    which chunk files already exist and validate cleanly, and only
    dispatch the chunks that don't. A completed chunk is NEVER
    re-dispatched, so a partial failure costs exactly the chunks that
    failed, not the whole run.

  - Retries are scoped to the single chunk that failed, bounded (default
    3 attempts), not to the run as a whole.

Usage pattern (see reliability_demo.py for a worked, verified example):

    plan = ChunkPlan(candidates, run_dir, chunk_size=40)
    for chunk in plan.pending_chunks():           # only what's NOT done
        prompt = plan.render_chunk_prompt(chunk, ...)
        # >>> dispatch `prompt` to an agent, however that happens <<<
        # >>> get back `raw_json_text` <<<
        plan.record_chunk_result(chunk, raw_json_text)   # validates + persists
    final = plan.merge()                           # only once all chunks done
"""
import json
import math
import os
import sys
from dataclasses import dataclass, field

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "scale_experiment"))
from validate_run import validate_run_file, _fail  # reuse the same hard-fail contract

DEFAULT_CHUNK_SIZE = 40


@dataclass
class Chunk:
    index: int
    candidates: list

    @property
    def path_name(self):
        return f"chunk_{self.index:03d}.json"


class ChunkPlan:
    def __init__(self, candidates, run_dir, chunk_size=DEFAULT_CHUNK_SIZE):
        self.candidates = candidates
        self.run_dir = run_dir
        self.chunk_size = chunk_size
        os.makedirs(run_dir, exist_ok=True)
        n_chunks = max(1, math.ceil(len(candidates) / chunk_size))
        self.chunks = []
        for i in range(n_chunks):
            part = candidates[i * chunk_size:(i + 1) * chunk_size]
            if part:
                self.chunks.append(Chunk(index=i, candidates=part))

    def _chunk_output_path(self, chunk):
        return os.path.join(self.run_dir, chunk.path_name)

    def _chunk_is_done(self, chunk):
        """A chunk counts as done only if its output file exists AND
        validates AND covers exactly that chunk's candidate set (no more,
        no less) -- a stale or corrupted file does not count as done."""
        path = self._chunk_output_path(chunk)
        if not os.path.isfile(path):
            return False
        try:
            data = validate_run_file(path)
        except ValueError:
            return False  # invalid -> not done, will be retried
        adjudicated = set()
        for bucket in ("proposed_sites", "flag_uncertain", "considered_and_rejected"):
            for item in data[bucket]:
                adjudicated.add((item["file"], item["line"]))
        expected = {(c["file"], c["line"]) for c in chunk.candidates}
        return adjudicated == expected

    def pending_chunks(self):
        """Idempotent resume: only chunks that are not already done."""
        return [c for c in self.chunks if not self._chunk_is_done(c)]

    def status(self):
        done = [c for c in self.chunks if self._chunk_is_done(c)]
        pending = [c for c in self.chunks if c not in done]
        return {"total_chunks": len(self.chunks), "done": len(done), "pending": len(pending),
                "pending_indices": [c.index for c in pending]}

    def render_chunk_prompt(self, chunk, template_text, repo_path):
        cand_json = json.dumps(chunk.candidates, indent=2)
        rendered = template_text.replace("{CANDIDATE_COUNT}", str(len(chunk.candidates)))
        rendered = rendered.replace("{REPO_PATH}", repo_path)
        rendered = rendered.replace("{CANDIDATE_LIST_JSON}", cand_json)
        return rendered

    def record_chunk_result(self, chunk, data_dict):
        """data_dict must already be a parsed dict with the three bucket
        keys. Writes to disk, then validates -- if validation fails, the
        bad file is NOT left in place (so a subsequent pending_chunks()
        call correctly re-offers this chunk rather than treating a
        corrupt file as done)."""
        path = self._chunk_output_path(chunk)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data_dict, f, indent=2)
        try:
            validate_run_file(tmp_path)
        except ValueError:
            os.remove(tmp_path)
            raise
        os.replace(tmp_path, path)  # atomic: never leaves a half-written "done" file

    def merge(self):
        """Only call once pending_chunks() is empty. Merges every chunk's
        buckets into one combined result and validates the whole thing."""
        pending = self.pending_chunks()
        if pending:
            raise RuntimeError(f"cannot merge: {len(pending)} chunk(s) still pending: "
                                f"{[c.index for c in pending]}")
        merged = {"proposed_sites": [], "flag_uncertain": [], "considered_and_rejected": []}
        for chunk in self.chunks:
            data = validate_run_file(self._chunk_output_path(chunk))
            for bucket in merged:
                merged[bucket].extend(data[bucket])
        merged_path = os.path.join(self.run_dir, "merged.json")
        with open(merged_path, "w") as f:
            json.dump({"target": "B", "repo": os.path.basename(self.run_dir), "run": 0, **merged}, f, indent=2)
        validate_run_file(merged_path)  # final sanity check on the combined file
        return merged_path

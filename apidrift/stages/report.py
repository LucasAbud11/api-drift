"""Writes the single human-readable artifact: report.md. Written only to
workdir -- never touches the repo under test."""
import os


def write(workdir, expanded_merged, stats, factblock, vocabulary,
          fixgen_expanded=None, verification_report=None):
    path = os.path.join(workdir, "report.md")
    lines = []
    lines.append("# api-drift run report")
    lines.append("")
    lines.append("This tool proposes; it does not push and does not open a PR. "
                  "Review every site below before applying anything.")
    lines.append("")
    lines.append(f"- Package: `{factblock['package_name']}`")
    lines.append(f"- Facts derived: {len(factblock['facts'])}")
    lines.append(f"- Vocabulary patterns: {len(vocabulary['patterns'])}")
    lines.append(f"- Raw candidates (grep): {stats.get('start', 0)}")
    lines.append(f"- Dropped by prefilter stage A (file irrelevance): {stats.get('dropped_by_A', 0)}")
    lines.append(f"- Dropped by prefilter stage B (comment/docstring): {stats.get('dropped_by_B', 0)}")
    lines.append(f"- Collapsed as duplicates by stage C: {stats.get('collapsed_by_C', 0)}")
    lines.append(f"- Adjudicated (post-filter, pre-expansion): {stats.get('final', 0)}")
    lines.append("")
    lines.append(f"## PROPOSE ({len(expanded_merged['proposed_sites'])})")
    lines.append("")
    for item in sorted(expanded_merged["proposed_sites"], key=lambda x: (x["file"], x["line"])):
        lines.append(f"- `{item['file']}:{item['line']}` (fact {item.get('pattern', '?')}) "
                      f"-- {item['reason']}")
        lines.append(f"  ```\n  {item['snippet']}\n  ```")
    lines.append("")
    lines.append(f"## FLAG-UNCERTAIN ({len(expanded_merged['flag_uncertain'])})")
    lines.append("")
    for item in sorted(expanded_merged["flag_uncertain"], key=lambda x: (x["file"], x["line"])):
        lines.append(f"- `{item['file']}:{item['line']}` -- {item['reason']}")
        lines.append(f"  ```\n  {item['snippet']}\n  ```")
    lines.append("")
    lines.append(f"## REJECT ({len(expanded_merged['considered_and_rejected'])})")
    lines.append("")
    lines.append("Not shown in detail -- these were confidently ruled out. "
                  "Full list in adjudication/merged.json.")
    lines.append("")

    if fixgen_expanded is not None:
        verify_by_site = {}
        if verification_report is not None:
            for item in verification_report["parse_and_line_match"]["items"]:
                verify_by_site[(item["file"], item["line"])] = item
        install_by_site = {}
        if verification_report is not None and verification_report["install"]["available"]:
            for item in verification_report["install"]["items"]:
                install_by_site[(item["file"], item["line"])] = item

        lines.append(f"## FIX ({len(fixgen_expanded['fixes'])})")
        lines.append("")
        lines.append("This tool proposes; it does not apply anything automatically. "
                      "Review the diff for each site below before applying it yourself.")
        lines.append("")
        for item in sorted(fixgen_expanded["fixes"], key=lambda x: (x["file"], x["line"])):
            key = (item["file"], item["line"])
            v = verify_by_site.get(key)
            badges = []
            if v is not None:
                badges.append("line-match OK" if v.get("line_match_ok") else "LINE-MATCH FAILED")
            file_parse = (verification_report["parse_and_line_match"]["file_parse_results"]
                          .get(item["file"]) if verification_report else None)
            if file_parse is not None:
                badges.append("parses OK" if file_parse.get("parses") else "PARSE FAILED")
            inst = install_by_site.get(key)
            if inst is not None:
                badges.append("import resolved" if inst.get("resolved") else "IMPORT DID NOT RESOLVE")
            if item.get("group_id"):
                badges.append(f"coordinated group {item['group_id']}")
            badge_text = f" [{', '.join(badges)}]" if badges else ""
            span_text = f":{item['line']}" if item["end_line"] == item["line"] \
                else f":{item['line']}-{item['end_line']}"
            lines.append(f"- `{item['file']}{span_text}`{badge_text} -- {item['reason']}")
            orig_diff = "\n".join(f"  - {l}" for l in item["original_lines"])
            prop_diff = "\n".join(f"  + {l}" for l in item["proposed_lines"])
            lines.append(f"  ```diff\n{orig_diff}\n{prop_diff}\n  ```")
        lines.append("")

        all_flagged = fixgen_expanded["flagged_for_human"]
        span_flagged = [it for it in all_flagged if it.get("flag_source") == "multiline_span_guard"]
        _GROUP_FLAG_SOURCES = (
            "multiline_span_guard", "group_consistency_guard",
            "value_flow_guard", "joint_resolution_declined",
            "unresolved_dependency_guard",
        )
        model_flagged = [it for it in all_flagged if it.get("flag_source") not in _GROUP_FLAG_SOURCES]
        # A group's cross-reference lives on every flagged_for_human entry
        # that's a member of one -- not only the ones whose flag_source IS
        # group_consistency_guard. A group whose only confirmed member was
        # already declined by the multi-line-span guard (the real shape on
        # both run-azeroth and run-youtrack-v2) never produces a
        # group_consistency_guard entry of its own -- group_id/group_members
        # are attached directly to that multiline_span_guard entry instead
        # (see fixgen.run()'s pass 1), so this section still renders it.
        group_flagged = [it for it in all_flagged if it.get("group_id")]
        n_categories = sum(1 for bucket in (span_flagged, group_flagged, model_flagged) if bucket)

        lines.append(f"## FLAG-FOR-HUMAN ({len(all_flagged)})")
        lines.append("")
        lines.append("Confirmed as a required change, but not a confident single-line fix -- "
                      "a structural refactor or a genuine judgment call. Needs a human.")
        lines.append("")

        if span_flagged:
            lines.append(f"### Not evaluated -- multi-line statement ({len(span_flagged)})")
            lines.append("")
            lines.append("These were never sent to the model. The line falls inside a "
                          "statement that spans more than one physical line (e.g. a "
                          "multi-line call); fixgen only ever rewrites one line, so it "
                          "cannot safely tell whether the rest of the statement also needs "
                          "to change. This is the tool declining to judge, not the model "
                          "hedging.")
            lines.append("")
            for item in sorted(span_flagged, key=lambda x: (x["file"], x["line"])):
                lines.append(f"- `{item['file']}:{item['line']}` -- {item['reason']}")
            lines.append("")

        if group_flagged:
            by_group = {}
            for item in group_flagged:
                by_group.setdefault(item.get("group_id", "?"), []).append(item)

            lines.append(f"### Coupled edit group -- declined together "
                          f"({len(by_group)} group(s), {len(group_flagged)} site(s))")
            lines.append("")
            lines.append("Each group below is one migration fact that needs coordinated "
                          "edits at more than one site -- fixing only the site(s) below "
                          "without also addressing every other member of the same group "
                          "leaves the group broken, the exact failure a real run "
                          "(tonyzorin/youtrack-mcp) produced. **Apply, or write by hand, "
                          "every member of a group together or not at all.** A member "
                          "marked \"not confirmed by adjudication\" was never a proposed "
                          "site in its own right -- it is shown only because a confirmed "
                          "site in this group depends on it.")
            lines.append("")
            for gid in sorted(by_group):
                items = by_group[gid]
                # group_members is identical (same group) on every item in
                # this bucket -- any one of them has the full roster.
                members = items[0].get("group_members", [])
                lines.append(f"**Group `{gid}`** ({len(members)} site(s))")
                lines.append("")
                by_key = {(it["file"], it["line"]): it for it in items}
                for m in sorted(members, key=lambda x: (x["file"], x["line"])):
                    key = (m["file"], m["line"])
                    matching = by_key.get(key)
                    if matching is not None and matching.get("flag_source") == "group_consistency_guard":
                        status = "declined here, was a confirmed site"
                    elif matching is not None and matching.get("flag_source") == "multiline_span_guard":
                        # A confirmed site in this group -- see "Not evaluated
                        # -- multi-line statement" above for its own entry.
                        status = "declined above as a multi-line statement, not repeated here"
                    elif matching is not None and matching.get("flag_source") == "value_flow_guard":
                        status = "declined here -- a jointly-resolved fix was rejected by the value-flow guard"
                    elif matching is not None and matching.get("flag_source") == "joint_resolution_declined":
                        status = "declined here -- the model itself chose not to resolve this group jointly"
                    elif matching is not None and matching.get("flag_source") == "unresolved_dependency_guard":
                        status = ("declined here -- shipped as a fix independently, but its own "
                                  "dependency elsewhere in this group did not also ship as a fix")
                    elif key in {(f["file"], f["line"]) for f in fixgen_expanded.get("fixes", [])}:
                        # Blocking is directional (see fixgen.py's run()):
                        # this member's own correctness didn't depend on
                        # whatever else in this group declined, so it was
                        # fixed independently -- see FIX above -- even
                        # though it still shares this group's roster for
                        # visibility.
                        status = "fixed independently -- see FIX above"
                    elif m.get("role") == "uncertain":
                        status = "not confirmed by adjudication (flag-uncertain) -- context only"
                    else:
                        # A confirmed site in this group that neither guard
                        # declined -- it either reached the model as its own
                        # ordinary site, or is still pending in another
                        # chunk. Named here for completeness only.
                        status = "not declined by this guard"
                    lines.append(f"- `{m['file']}:{m['line']}` ({status}) -- {m['reason']}")
                lines.append("")

        if model_flagged:
            if n_categories > 1:
                lines.append(f"### Model judgment call ({len(model_flagged)})")
                lines.append("")
            for item in sorted(model_flagged, key=lambda x: (x["file"], x["line"])):
                lines.append(f"- `{item['file']}:{item['line']}` -- {item['reason']}")
            lines.append("")

        if verification_report is not None:
            install = verification_report["install"]
            lines.append("## Verification")
            lines.append("")
            lines.append("- Tier 1 (parse + claimed-original-line match): always runs, no "
                          "external dependency.")
            if install["available"]:
                n_ok = sum(1 for r in install["items"] if r["resolved"])
                lines.append(f"- Tier 2 (real install, isolated venv): {n_ok}/{len(install['items'])} "
                              f"touched import(s) resolved against the real installed package.")
            else:
                lines.append(f"- Tier 2 (real install): unavailable -- {install['reason']}. "
                              f"Fixes below are verified at tier 1 only; treat them with tier-1, "
                              f"not tier-2, confidence.")
            lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path

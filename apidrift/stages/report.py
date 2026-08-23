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
            badge_text = f" [{', '.join(badges)}]" if badges else ""
            lines.append(f"- `{item['file']}:{item['line']}`{badge_text} -- {item['reason']}")
            lines.append(f"  ```diff\n  - {item['original_line']}\n  + {item['proposed_line']}\n  ```")
        lines.append("")

        lines.append(f"## FLAG-FOR-HUMAN ({len(fixgen_expanded['flagged_for_human'])})")
        lines.append("")
        lines.append("Confirmed as a required change, but not a confident single-line fix -- "
                      "a structural refactor or a genuine judgment call. Needs a human.")
        lines.append("")
        for item in sorted(fixgen_expanded["flagged_for_human"], key=lambda x: (x["file"], x["line"])):
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

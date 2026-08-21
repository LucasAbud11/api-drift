"""Writes the single human-readable artifact: report.md. Written only to
workdir -- never touches the repo under test."""
import os


def write(workdir, expanded_merged, stats, factblock, vocabulary):
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

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path

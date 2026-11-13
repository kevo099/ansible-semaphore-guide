#!/usr/bin/env python3
"""Summarize one XCCDF TestResult without inventing a compliance percentage.

summarize_xccdf.py RESULTS.xml [--result-id ID] [--findings FILE.csv] [--tailoring TAILORING.xml]
  prints the outcome counts, the content and STIG release the scan measured, and
  the failing rules by DISA severity category. --findings also writes every rule
  that still needs a reader (fail, error, unknown, notchecked) to a CSV file with
  its category, STIG ID and rule ID. --tailoring names the exceptions file the
  scan used, so that the profile it extends can be described.
summarize_xccdf.py --tailoring TAILORING.xml
  describes an XCCDF tailoring file alone: its profile, the profile it extends
  and the rules it leaves out.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


NAMESPACES = {"http://checklists.nist.gov/xccdf/1.1", "http://checklists.nist.gov/xccdf/1.2"}
OUTCOMES = (
    "pass", "fail", "notapplicable", "notchecked", "notselected",
    "error", "unknown", "informational", "fixed",
)
# DISA's severity categories for the XCCDF severities; any other severity has none.
CATEGORIES = {"high": "CAT I", "medium": "CAT II", "low": "CAT III"}
UNRATED = "unrated"
# The outcomes a reader still has to fix or assess by hand.
OPEN_OUTCOMES = ("fail", "error", "unknown", "notchecked")
# A STIG ID as DISA writes it, such as RHEL-09-211010 or UBTU-24-100010.
STIG_ID = re.compile(r"[A-Z][A-Z0-9]{1,7}-\d{2}-\d{6}")
# DISA numbers a benchmark 002.010 for Version 2, Release 10.
DISA_BENCHMARK = re.compile(r"0*(\d+)\.0*(\d+)")


def local(node):
    return node.tag.rsplit("}", 1)[-1]


def child_text(node, name):
    """The text of the first child with this local name, on one line."""
    for child in node:
        if local(child) == name:
            return " ".join("".join(child.itertext()).split())
    return ""


def select_result(root, result_id=None):
    results = [node for node in root.iter() if node.tag in {f"{{{ns}}}TestResult" for ns in NAMESPACES}]
    if result_id is not None:
        results = [node for node in results if node.get("id") == result_id]
    if len(results) != 1:
        raise ValueError("Expected one TestResult; select an exact --result-id if the XML contains several")
    return results[0], results[0].tag.split("}", 1)[0] + "}"


def rule_index(root, ns):
    """Title, severity and STIG IDs of each rule the results file carries.

    The vendors' content names a STIG ID in a rule's references; DISA's own
    benchmarks name it in the rule's version. Content without either, such as
    Rocky Linux's, yields no STIG ID, and the rule ID then identifies the rule.
    """
    index = {}
    for rule in root.iter(ns + "Rule"):
        stig_ids = set()
        for child in rule:
            if local(child) in ("version", "reference"):
                value = (child.text or "").strip()
                if STIG_ID.fullmatch(value):
                    stig_ids.add(value)
        index[rule.get("id")] = {"title": child_text(rule, "title"), "severity": rule.get("severity"),
                                 "stig_ids": sorted(stig_ids)}
    return index


def short_rule(rule_id):
    """The part of a rule ID after the benchmark's prefix."""
    return rule_id.split("_rule_", 1)[-1]


def describe_content(root, result, ns, tailoring=None):
    """Which benchmark, profile and STIG release the scan measured, as the content states them."""
    benchmark = root if local(root) == "Benchmark" else next(iter(root.iter(ns + "Benchmark")), None)
    source = result.find(ns + "benchmark")
    profile_ref = result.find(ns + "profile")
    profile_id = profile_ref.get("idref") if profile_ref is not None else None
    # A tailored scan reports the tailoring's profile; the release is that of the profile it extends.
    base_id = tailoring["extends"] if tailoring and tailoring["profile_id"] == profile_id else profile_id
    content = {
        "benchmark_id": benchmark.get("id") if benchmark is not None else (source.get("id") if source is not None else None),
        "benchmark_title": child_text(benchmark, "title") if benchmark is not None else "",
        "benchmark_version": child_text(benchmark, "version") if benchmark is not None else "",
        "release_info": "",
        "file": source.get("href") if source is not None else None,
        "profile_id": base_id,
        "profile_title": "",
        "profile_version": "",
        "scanner": result.get("test-system"),
        "stig_release": None,
    }
    if benchmark is not None:
        for child in benchmark:
            if local(child) == "plain-text" and child.get("id") == "release-info":
                content["release_info"] = " ".join((child.text or "").split())
        for profile in benchmark.iter(ns + "Profile"):
            if profile.get("id") == base_id:
                content["profile_title"] = child_text(profile, "title")
                content["profile_version"] = child_text(profile, "version")
    disa = DISA_BENCHMARK.fullmatch(content["benchmark_version"])
    if re.fullmatch(r"V\d+R\d+", content["profile_version"]):
        content["stig_release"] = content["profile_version"]
    elif disa and (content["benchmark_id"] or "").startswith("xccdf_mil.disa.stig_benchmark"):
        content["stig_release"] = f"V{disa.group(1)}R{disa.group(2)}"
    release = f"STIG release {content['stig_release']}" if content["stig_release"] else "STIG release not stated by the content"
    if content["release_info"]:
        release += f" ({content['release_info']})"
    profile = f"profile '{content['profile_title'] or base_id}'"
    origin = f"in '{content['benchmark_title']}' {content['benchmark_version']}".rstrip() if content["benchmark_title"] else ""
    scanner = f"scanner {content['scanner']}" if content["scanner"] else ""
    content["line"] = f"{release}: " + ", ".join(part for part in (
        " ".join(part for part in (profile, origin) if part),
        f"file {content['file']}" if content["file"] else "", scanner) if part)
    return content


def open_findings(root, result_id=None):
    """Every assessed rule that still needs a reader, most severe first."""
    result, ns = select_result(root, result_id)
    rules = rule_index(root, ns)
    rows = {}
    for rule in result.findall(ns + "rule-result"):
        outcome = (rule.findtext(ns + "result") or "").strip()
        if outcome not in OPEN_OUTCOMES:
            continue
        rule_id = rule.get("idref")
        known = rules.get(rule_id, {})
        severity = (rule.get("severity") or known.get("severity") or "unknown").lower()
        rows[(rule_id, outcome)] = {
            "category": CATEGORIES.get(severity, UNRATED), "severity": severity, "result": outcome,
            "stig_ids": known.get("stig_ids", []), "rule_id": rule_id, "title": known.get("title", ""),
        }
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(rows.values(), key=lambda row: (order.get(row["severity"], 3), OPEN_OUTCOMES.index(row["result"]),
                                                  row["stig_ids"], row["rule_id"]))


def summarize(root, result_id=None, tailoring=None):
    selected, ns = select_result(root, result_id)
    counts = Counter({value: 0 for value in OUTCOMES})
    by_outcome = defaultdict(set)
    instances_by_rule = Counter()
    for rule in selected.findall(ns + "rule-result"):
        rule_id = rule.get("idref")
        outcomes = rule.findall(ns + "result")
        if not rule_id or len(outcomes) != 1:
            raise ValueError("A rule-result is missing its ID or single outcome")
        value = (outcomes[0].text or "").strip()
        if value not in OUTCOMES:
            raise ValueError("Unrecognized rule outcome; inspect the original XML")
        counts[value] += 1
        by_outcome[value].add(rule_id)
        instances_by_rule[rule_id] += 1
    if not instances_by_rule:
        raise ValueError("No assessed rule-result instances; this is not a completed assessment")
    # OpenSCAP lists every rule in the benchmark and marks those the profile left out
    # notselected, so only the other outcomes come from rules the profile assessed.
    selected_rules = set().union(*(by_outcome[value] for value in OUTCOMES if value != "notselected"))
    if not selected_rules:
        raise ValueError("Every rule-result is notselected, so the profile assessed nothing; "
                         "check the profile ID and any tailoring")
    profile = selected.find(ns + "profile")
    failed = [row for row in open_findings(root, result_id) if row["result"] == "fail"]
    by_category = Counter({name: 0 for name in list(CATEGORIES.values()) + [UNRATED]})
    by_category.update(row["category"] for row in failed)
    report = {
        "result_id": selected.get("id"),
        "profile": profile.get("idref") if profile is not None else None,
        "result_instances": sum(counts.values()),
        "unique_rule_ids": len(instances_by_rule),
        "selected_result_instances": sum(counts.values()) - counts["notselected"],
        "selected_rule_ids": len(selected_rules),
        "rules_with_repeated_instances": sum(value > 1 for value in instances_by_rule.values()),
        "outcome_instances": dict(counts),
        "distinct_rule_ids_per_outcome": {value: len(by_outcome[value]) for value in OUTCOMES},
        "has_scanner_errors_or_unknowns": bool(counts["error"] or counts["unknown"]),
        "content": describe_content(root, selected, ns, tailoring),
        "failed_by_category": dict(by_category),
        # One line per failing CAT I rule: its STIG ID where the content has one, its rule and title.
        "failed_cat_i": [" ".join(row["stig_ids"] + [f"({short_rule(row['rule_id'])}):", row["title"]]).strip()
                         for row in failed if row["category"] == "CAT I"],
        # The same rules by STIG ID alone, or by rule name where the content has no STIG ID.
        # A rule that answers several STIG IDs joins them with a slash.
        "failed_cat_i_ids": ["/".join(row["stig_ids"]) or short_rule(row["rule_id"])
                             for row in failed if row["category"] == "CAT I"],
        "note": "Distinct rule IDs can overlap between outcome categories. result_instances and unique_rule_ids "
                "include notselected rules, which the profile did not assess; the selected_ totals leave them out. "
                "No compliance percentage is calculated.",
    }
    if tailoring:
        report["tailoring"] = {key: tailoring[key] for key in ("tailoring_id", "profile_id", "extends", "left_out_count",
                                                               "values_set", "rules_refined_count", "sha256")
                               if key in tailoring}
    return report


def describe_tailoring(root):
    """The profile an XCCDF tailoring file defines, the profile it extends and what it leaves out."""
    namespace = root.tag.split("}", 1)[0].lstrip("{") if root.tag.startswith("{") else ""
    if local(root) != "Tailoring" or namespace != "http://checklists.nist.gov/xccdf/1.2":
        raise ValueError("Not an XCCDF 1.2 tailoring file: its root element is not Tailoring")
    ns = "{" + namespace + "}"
    profiles = root.findall(ns + "Profile")
    if len(profiles) != 1:
        raise ValueError(f"Expected one Profile in the tailoring file, found {len(profiles)}")
    profile = profiles[0]
    if not profile.get("id") or not profile.get("extends"):
        raise ValueError("The tailoring file's Profile needs an id and the profile it extends")
    # selected is an XML boolean: 0 and 1 mean the same as false and true.
    selections = profile.findall(ns + "select")
    left_out = sorted({node.get("idref") for node in selections
                       if (node.get("selected") or "").strip() in ("false", "0") and node.get("idref")})
    # refine-rule changes a rule's role, severity or weight; role "unchecked" stops its check.
    refined = sorted({node.get("idref") for node in profile.findall(ns + "refine-rule") if node.get("idref")})
    benchmark = root.find(ns + "benchmark")
    return {
        "tailoring_id": root.get("id"),
        "benchmark": benchmark.get("href") if benchmark is not None else None,
        "profile_id": profile.get("id"),
        "extends": profile.get("extends"),
        "title": child_text(profile, "title"),
        "left_out": left_out,
        "left_out_count": len(left_out),
        "selected_count": sum((node.get("selected") or "").strip() in ("true", "1") for node in selections),
        "values_set": len(profile.findall(ns + "set-value")) + len(profile.findall(ns + "refine-value")),
        "rules_refined": refined,
        "rules_refined_count": len(refined),
    }


def write_findings(path, rows):
    """One CSV row per open rule. A leading quote keeps a spreadsheet from running a cell as a formula.

    Every cell comes from the scanned machine's results, so every cell is guarded: one
    that starts with =, +, - or @, also behind white space, or with a tab or a carriage return.
    """
    def cell(value):
        value = "" if value is None else str(value)
        risky = value[:1] in ("\t", "\r") or value.lstrip()[:1] in ("=", "+", "-", "@")
        return "'" + value if risky else value

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "severity", "result", "stig_id", "rule_id", "title"])
        for row in rows:
            writer.writerow([cell(value) for value in (row["category"], row["severity"], row["result"],
                                                       " ".join(row["stig_ids"]), row["rule_id"], row["title"])])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("xml", type=Path, nargs="?")
    parser.add_argument("--result-id")
    parser.add_argument("--findings", type=Path, help="write every rule that still needs a reader to this CSV file")
    parser.add_argument("--tailoring", type=Path, help="the XCCDF tailoring (exceptions) file the scan used")
    args = parser.parse_args()
    if args.xml is None and args.tailoring is None:
        parser.error("name a results file, a --tailoring file, or both")
    tailoring = None
    try:
        if args.tailoring is not None:
            tailoring_data = args.tailoring.read_bytes()
            tailoring = describe_tailoring(ET.fromstring(tailoring_data))
            tailoring["sha256"] = hashlib.sha256(tailoring_data).hexdigest()
    except (OSError, ET.ParseError, ValueError, LookupError) as error:
        parser.exit(1, f"Cannot read the tailoring file: {error}\n")
    if args.xml is None:
        print(json.dumps(tailoring, indent=2))
        return
    try:
        data = args.xml.read_bytes()
        root = ET.fromstring(data)
        report = summarize(root, args.result_id, tailoring)
        if args.findings is not None:
            rows = open_findings(root, args.result_id)
            write_findings(args.findings, rows)
            report["findings_file"] = str(args.findings)
            report["findings_listed"] = len(rows)
    except (OSError, ET.ParseError, ValueError, LookupError) as error:
        parser.exit(1, f"Cannot summarize assessment: {error}\n")
    report["source_sha256"] = hashlib.sha256(data).hexdigest()
    print(json.dumps(report, indent=2))
    # Zero means valid parsing without error/unknown outcomes, not compliance.
    raise SystemExit(2 if report["has_scanner_errors_or_unknowns"] else 0)


if __name__ == "__main__":
    main()

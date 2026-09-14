#!/usr/bin/env python3
"""Summarize one XCCDF TestResult without inventing a compliance percentage."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


NAMESPACES = {"http://checklists.nist.gov/xccdf/1.1", "http://checklists.nist.gov/xccdf/1.2"}
OUTCOMES = (
    "pass", "fail", "notapplicable", "notchecked", "notselected",
    "error", "unknown", "informational", "fixed",
)


def summarize(root, result_id=None):
    results = [node for node in root.iter() if node.tag in {f"{{{ns}}}TestResult" for ns in NAMESPACES}]
    if result_id is not None:
        results = [node for node in results if node.get("id") == result_id]
    if len(results) != 1:
        raise ValueError("Expected one TestResult; select an exact --result-id if the XML contains several")
    selected = results[0]
    ns = selected.tag.split("}", 1)[0] + "}"
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
    profile = selected.find(ns + "profile")
    return {
        "result_id": selected.get("id"),
        "profile": profile.get("idref") if profile is not None else None,
        "result_instances": sum(counts.values()),
        "unique_rule_ids": len(instances_by_rule),
        "rules_with_repeated_instances": sum(value > 1 for value in instances_by_rule.values()),
        "outcome_instances": dict(counts),
        "distinct_rule_ids_per_outcome": {value: len(by_outcome[value]) for value in OUTCOMES},
        "has_scanner_errors_or_unknowns": bool(counts["error"] or counts["unknown"]),
        "note": "Distinct rule IDs can overlap between outcome categories. No compliance percentage is calculated.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path)
    parser.add_argument("--result-id")
    args = parser.parse_args()
    try:
        data = args.xml.read_bytes()
        report = summarize(ET.fromstring(data), args.result_id)
    except (OSError, ET.ParseError, ValueError) as error:
        parser.exit(1, f"Cannot summarize assessment: {error}\n")
    report["source_sha256"] = hashlib.sha256(data).hexdigest()
    print(json.dumps(report, indent=2))
    # Zero means valid parsing without error/unknown outcomes, not compliance.
    raise SystemExit(2 if report["has_scanner_errors_or_unknowns"] else 0)


if __name__ == "__main__":
    main()

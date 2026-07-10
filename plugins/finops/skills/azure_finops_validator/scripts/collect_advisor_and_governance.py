#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - Account/Subscription-Scope Collector
------------------------------------------------------------------------------
Covers the rules that need subscription-scope signals rather than a single
resource record: Azure Advisor cost recommendations (AZFO-018), Cost
Management budgets (AZFO-017), and the Dev/Test pricing offer check
(AZFO-019). Idle load balancer/App Gateway detection (AZFO-008) and
FinOps-tooling sprawl (AZFO-024) still require manual review — see
references/finops_rules.json for their detection logic.

Output is a JSON list of findings in the same schema validate_resources.py
produces, meant to be passed to validate_resources.py via --extra-findings.

Usage:
    python3 collect_advisor_and_governance.py \
        --subscription-id <sub-id> \
        --rules references/finops_rules.json \
        --output account_scope_findings.json \
        [--assume-devtest-subscription]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


def run_az(args, timeout=90):
    result = subprocess.run(["az"] + args + ["-o", "json"], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500])
    return json.loads(result.stdout) if result.stdout.strip() else None


def warn(msg):
    print(f"  [warn] {msg}", file=sys.stderr)


def collect_advisor_findings(subscription_id, rule):
    findings = []
    try:
        recs = run_az([
            "advisor", "recommendation", "list",
            "--subscription", subscription_id,
            "--category", "Cost",
        ]) or []
    except Exception as e:
        warn(f"Advisor recommendation list failed (Advisor may need a few hours after enablement to populate): {e}")
        return findings

    now = datetime.now(timezone.utc)
    for rec in recs:
        last_updated_str = rec.get("lastUpdated")
        age_days = None
        if last_updated_str:
            try:
                last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                age_days = (now - last_updated).days
            except ValueError:
                pass
        if age_days is None or age_days <= 30:
            continue  # rule only flags recommendations open for 30+ days
        impacted = rec.get("impactedValue") or rec.get("resourceMetadata", {}).get("resourceId", "unknown")
        findings.append({
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "severity": rule["severity"],
            "category": rule["category"],
            "domain": rule["domain"],
            "resource_id": rec.get("resourceMetadata", {}).get("resourceId"),
            "resource_name": impacted,
            "resource_type": rec.get("impactedField"),
            "resource_group": None,
            "location": None,
            "finding_detail": f"Advisor recommendation '{rec.get('shortDescription', {}).get('problem', rec.get('category'))}' "
                               f"has been open for {age_days} days without action.",
            "remediation": rule["remediation"] + f" Advisor solution: "
                           f"{rec.get('shortDescription', {}).get('solution', 'see Advisor for details')}.",
            "estimated_savings": rule["estimated_savings"],
            "monthly_cost_usd": rec.get("extendedProperties", {}).get("savingsAmount"),
        })
    return findings


def collect_budget_findings(subscription_id, rule):
    findings = []
    try:
        budgets = run_az(["consumption", "budget", "list", "--subscription", subscription_id]) or []
    except Exception as e:
        warn(f"Consumption budget list failed (continuing): {e}")
        return findings
    if not budgets:
        findings.append({
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "severity": rule["severity"],
            "category": rule["category"],
            "domain": rule["domain"],
            "resource_id": f"/subscriptions/{subscription_id}",
            "resource_name": subscription_id,
            "resource_type": "Microsoft.Subscription",
            "resource_group": None,
            "location": None,
            "finding_detail": "No Cost Management budgets are configured at the subscription scope.",
            "remediation": rule["remediation"],
            "estimated_savings": rule["estimated_savings"],
            "monthly_cost_usd": None,
        })
    return findings


def collect_devtest_offer_finding(subscription_id, rule, assume_devtest):
    if not assume_devtest:
        return []
    try:
        account = run_az(["account", "show", "--subscription", subscription_id])
    except Exception as e:
        warn(f"account show failed (continuing): {e}")
        return []
    offer = (account or {}).get("subscriptionPolicies", {}).get("quotaId", "") or account.get("offerType", "") or ""
    if "devtest" not in offer.lower() and "msdn" not in offer.lower():
        return [{
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "severity": rule["severity"],
            "category": rule["category"],
            "domain": rule["domain"],
            "resource_id": f"/subscriptions/{subscription_id}",
            "resource_name": subscription_id,
            "resource_type": "Microsoft.Subscription",
            "resource_group": None,
            "location": None,
            "finding_detail": f"Subscription flagged as non-production is on offer type "
                               f"'{offer or 'unknown'}', not a Dev/Test pricing offer.",
            "remediation": rule["remediation"],
            "estimated_savings": rule["estimated_savings"],
            "monthly_cost_usd": None,
        }]
    return []


def main():
    parser = argparse.ArgumentParser(description="Collect Advisor/budget/subscription-scope FinOps findings.")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--rules", default="references/finops_rules.json")
    parser.add_argument("--output", default="account_scope_findings.json")
    parser.add_argument("--assume-devtest-subscription", action="store_true",
                         help="Set this only if the subscription is known to host exclusively non-production workloads")
    args = parser.parse_args()

    ruleset = json.load(open(args.rules))
    rules_by_id = {r["rule_id"]: r for r in ruleset["rules"]}

    findings = []
    print("Collecting Azure Advisor cost recommendations (AZFO-018)...")
    findings += collect_advisor_findings(args.subscription_id, rules_by_id["AZFO-018"])
    print("Checking Cost Management budgets (AZFO-017)...")
    findings += collect_budget_findings(args.subscription_id, rules_by_id["AZFO-017"])
    print("Checking Dev/Test pricing offer eligibility (AZFO-019)...")
    findings += collect_devtest_offer_finding(args.subscription_id, rules_by_id["AZFO-019"], args.assume_devtest_subscription)

    with open(args.output, "w") as f:
        json.dump(findings, f, indent=2)
    print(f"Wrote {len(findings)} account/subscription-scope findings to {args.output}")


if __name__ == "__main__":
    sys.exit(main())

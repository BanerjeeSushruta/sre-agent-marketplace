#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - End-to-End Orchestrator
-------------------------------------------------------------------
Runs the full pipeline against a live Azure subscription in one command:
  1. collect_azure_data.py            -> resource_inventory.json
  2. collect_advisor_and_governance.py -> account_scope_findings.json
  3. validate_resources.py            -> findings.json
  4. generate_report.py               -> PDF report

Intended to be invoked by an Azure SRE agent that is already authenticated
to Azure (managed identity / service principal / az login) with Reader,
Monitoring Reader, and (optionally) Cost Management Reader on the target
subscription.

Usage:
    python3 run_finops_validation.py \
        --subscription-id <sub-id> \
        --title "Contoso Production Subscription" \
        --output-dir /mnt/user-data/outputs \
        [--resource-groups rg-prod,rg-data] \
        [--assume-devtest-subscription] \
        [--skip-metrics] [--skip-cost]
"""

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
RULES_PATH = os.path.join(SKILL_ROOT, "references", "finops_rules.json")


def run_step(description, cmd):
    print(f"\n=== {description} ===")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"ERROR: step failed ({description}). Aborting pipeline.", file=sys.stderr)
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Run the full live Azure FinOps validation pipeline.")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-groups", help="Comma-separated resource group names to restrict scope to")
    parser.add_argument("--title", default="Azure Subscription", help="Scope name shown on the report cover page")
    parser.add_argument("--output-dir", default=".", help="Directory to write the working files and final PDF into")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--assume-devtest-subscription", action="store_true")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip Monitor metrics calls (faster, structural checks only)")
    parser.add_argument("--skip-cost", action="store_true", help="Skip the Cost Management query")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    inventory_path = os.path.join(args.output_dir, "resource_inventory.json")
    account_findings_path = os.path.join(args.output_dir, "account_scope_findings.json")
    findings_path = os.path.join(args.output_dir, "findings.json")
    pdf_path = os.path.join(args.output_dir, "AzureFinOps_Validation_Report.pdf")

    collect_cmd = [
        sys.executable, os.path.join(SCRIPT_DIR, "collect_azure_data.py"),
        "--subscription-id", args.subscription_id,
        "--output", inventory_path,
        "--lookback-days", str(args.lookback_days),
    ]
    if args.resource_groups:
        collect_cmd += ["--resource-groups", args.resource_groups]
    if args.skip_metrics:
        collect_cmd.append("--skip-metrics")
    if args.skip_cost:
        collect_cmd.append("--skip-cost")
    run_step("1/4 Collecting live Azure resource inventory", collect_cmd)

    governance_cmd = [
        sys.executable, os.path.join(SCRIPT_DIR, "collect_advisor_and_governance.py"),
        "--subscription-id", args.subscription_id,
        "--rules", RULES_PATH,
        "--output", account_findings_path,
    ]
    if args.assume_devtest_subscription:
        governance_cmd.append("--assume-devtest-subscription")
    run_step("2/4 Collecting Advisor / budget / subscription-scope findings", governance_cmd)

    validate_cmd = [
        sys.executable, os.path.join(SCRIPT_DIR, "validate_resources.py"),
        "--input", inventory_path,
        "--rules", RULES_PATH,
        "--output", findings_path,
        "--extra-findings", account_findings_path,
    ]
    run_step("3/4 Evaluating resources against the FinOps rule catalog", validate_cmd)

    report_cmd = [
        sys.executable, os.path.join(SCRIPT_DIR, "generate_report.py"),
        "--findings", findings_path,
        "--rules", RULES_PATH,
        "--output", pdf_path,
        "--title", args.title,
    ]
    run_step("4/4 Generating PDF remediation report", report_cmd)

    print(f"\nDone. Report: {pdf_path}")


if __name__ == "__main__":
    sys.exit(main())

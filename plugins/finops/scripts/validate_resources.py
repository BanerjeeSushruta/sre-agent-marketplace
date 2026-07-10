#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - Rules Engine
------------------------------------------------------
Evaluates an exported Azure resource inventory (see
references/azure-data-collection.md for how to produce one) against the
FinOps rule catalog in references/finops_rules.json, and writes a findings
JSON file consumed by generate_report.py.

Usage:
    python validate_resources.py \
        --input examples/sample_resource_inventory.json \
        --rules references/finops_rules.json \
        --output findings.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone

REQUIRED_TAGS = ["CostCenter", "Owner", "Environment", "Application"]


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def get_metric(resource, key, default=None):
    return (resource.get("metrics") or {}).get(key, default)


def get_prop(resource, key, default=None):
    return (resource.get("properties") or {}).get(key, default)


def get_tag(resource, key, default=None):
    return (resource.get("tags") or {}).get(key, default)


# ---------------------------------------------------------------------------
# Individual rule checks.
# Each function takes a resource dict and returns (matched: bool, detail: str)
# or None if the rule does not apply / required data is missing.
# ---------------------------------------------------------------------------

def check_AZFO_001(r):
    if r.get("type") != "Microsoft.Compute/virtualMachines":
        return None
    avg_cpu = get_metric(r, "avg_cpu_percent_14d")
    max_cpu = get_metric(r, "max_cpu_percent_14d")
    if avg_cpu is None or max_cpu is None:
        return None
    if avg_cpu < 5 and max_cpu < 20:
        return True, f"14-day avg CPU {avg_cpu}%, max CPU {max_cpu}% — right-sizing candidate."
    return False, None


def check_AZFO_002(r):
    if r.get("type") != "Microsoft.Compute/virtualMachines":
        return None
    avg_cpu = get_metric(r, "avg_cpu_percent_30d")
    net_bytes = get_metric(r, "network_bytes_30d")
    power_state = get_metric(r, "power_state")
    if avg_cpu is None or power_state is None:
        return None
    if avg_cpu < 1 and (net_bytes is None or net_bytes < 50000) and power_state == "running":
        return True, f"30-day avg CPU {avg_cpu}%, minimal network activity while running — idle VM."
    return False, None


def check_AZFO_003(r):
    if r.get("type") not in ("Microsoft.Compute/virtualMachines", "Microsoft.Compute/virtualMachineScaleSets"):
        return None
    uptime = get_metric(r, "uptime_ratio_30d")
    pricing_model = get_prop(r, "pricing_model", "payg")
    covered = get_prop(r, "reservation_or_savings_plan_covered", False)
    if uptime is None:
        return None
    if uptime > 0.9 and pricing_model == "payg" and not covered:
        return True, f"30-day uptime ratio {uptime:.0%} on pay-as-you-go pricing with no commitment discount."
    return False, None


def check_AZFO_004(r):
    if r.get("type") not in (
        "Microsoft.Compute/virtualMachines",
        "Microsoft.Sql/servers/databases",
        "Microsoft.SqlVirtualMachine/sqlVirtualMachines",
    ):
        return None
    license_type = get_prop(r, "licenseType", "None")
    os_type = get_prop(r, "osType", "")
    eligible = get_prop(r, "eligible_licenses_available", None)
    if eligible is None:
        return None
    is_licensed_os = os_type.lower() in ("windows", "sqlserver", "sql server")
    if is_licensed_os and eligible and license_type not in ("AHB", "Windows_Server", "Windows_Server_Perpetual"):
        return True, f"Eligible {os_type} workload without Azure Hybrid Benefit applied (licenseType={license_type})."
    return False, None


def check_AZFO_005(r):
    if r.get("type") != "Microsoft.Compute/disks":
        return None
    disk_state = get_prop(r, "diskState")
    days_unattached = get_prop(r, "days_unattached")
    if disk_state is None:
        return None
    if disk_state == "Unattached" and (days_unattached or 0) > 7:
        return True, f"Disk unattached for {days_unattached} days."
    return False, None


def check_AZFO_006(r):
    if r.get("type") != "Microsoft.Compute/disks":
        return None
    sku = r.get("sku", "")
    avg_iops = get_metric(r, "avg_iops_30d")
    provisioned_iops = get_prop(r, "provisioned_iops")
    if avg_iops is None or not provisioned_iops:
        return None
    if sku in ("Premium_LRS", "UltraSSD_LRS") and avg_iops < 0.2 * provisioned_iops:
        return True, f"{sku} disk averaging {avg_iops} IOPS against {provisioned_iops} provisioned."
    return False, None


def check_AZFO_007(r):
    if r.get("type") != "Microsoft.Network/publicIPAddresses":
        return None
    ip_config = get_prop(r, "ipConfiguration", "present")
    sku = r.get("sku", "")
    if ip_config in (None, "", "null") and sku == "Standard":
        return True, "Standard public IP with no associated ipConfiguration."
    return False, None


def check_AZFO_009(r):
    if r.get("type") != "Microsoft.Storage/storageAccounts":
        return None
    lifecycle = get_prop(r, "lifecycle_policy_configured")
    cold_bytes = get_prop(r, "hot_tier_bytes_not_accessed_30d")
    if lifecycle is None or cold_bytes is None:
        return None
    if lifecycle is False and cold_bytes > 0:
        return True, f"No lifecycle policy; {cold_bytes} bytes in hot tier untouched for 30+ days."
    return False, None


def check_AZFO_010(r):
    if r.get("type") != "Microsoft.Storage/storageAccounts":
        return None
    sku = r.get("sku", "")
    criticality = get_tag(r, "DataCriticality", "unknown")
    if sku in ("Standard_GRS", "Standard_RAGRS", "Standard_GZRS") and criticality != "high":
        return True, f"{sku} replication with DataCriticality tag = '{criticality}'."
    return False, None


def check_AZFO_011(r):
    if r.get("type") != "Microsoft.Compute/snapshots":
        return None
    age_days = get_prop(r, "age_days")
    retention_tag = get_tag(r, "Retention")
    if age_days is None:
        return None
    if age_days > 90 and not retention_tag:
        return True, f"Snapshot is {age_days} days old with no retention tag."
    return False, None


def check_AZFO_012(r):
    if r.get("type") not in ("Microsoft.Compute/virtualMachines", "Microsoft.Compute/virtualMachineScaleSets"):
        return None
    env = get_tag(r, "Environment", "").lower()
    auto_shutdown = get_prop(r, "auto_shutdown_configured")
    if auto_shutdown is None:
        return None
    if env in ("dev", "test", "qa") and not auto_shutdown:
        return True, f"Environment tag '{env}' with no auto-shutdown schedule configured."
    return False, None


def check_AZFO_013(r):
    if r.get("type") != "Microsoft.Web/serverfarms":
        return None
    avg_cpu = get_metric(r, "avg_cpu_percent_14d")
    instance_count = get_prop(r, "instance_count")
    autoscale = get_prop(r, "autoscale_configured")
    if avg_cpu is None or instance_count is None or autoscale is None:
        return None
    if avg_cpu < 15 and instance_count > 1 and not autoscale:
        return True, f"14-day avg CPU {avg_cpu}% across {instance_count} static instances, no autoscale."
    return False, None


def check_AZFO_014(r):
    if r.get("type") != "Microsoft.ContainerService/managedClusters":
        return None
    autoscaling = get_prop(r, "autoscaling_enabled")
    util = get_metric(r, "avg_node_cpu_requests_utilization_14d")
    if autoscaling is None or util is None:
        return None
    if not autoscaling and util < 40:
        return True, f"Fixed node pool size with {util}% avg CPU request utilization."
    return False, None


def check_AZFO_015(r):
    if r.get("type") not in ("Microsoft.Sql/servers/databases", "Microsoft.DocumentDB/databaseAccounts"):
        return None
    util = get_metric(r, "avg_dtu_or_ru_utilization_percent_14d")
    if util is None:
        return None
    if util < 25:
        return True, f"14-day avg provisioned-capacity utilization {util}%."
    return False, None


def check_AZFO_016(r):
    tags = r.get("tags") or {}
    missing = [t for t in REQUIRED_TAGS if t not in tags or not tags[t]]
    if missing:
        return True, f"Missing required tag(s): {', '.join(missing)}."
    return False, None


def check_AZFO_020(r):
    if r.get("type") not in ("Microsoft.Network/expressRouteCircuits", "Microsoft.Network/virtualNetworkGateways"):
        return None
    peak = get_metric(r, "peak_utilization_percent_30d")
    if peak is None:
        return None
    if peak < 30:
        return True, f"30-day peak utilization {peak}% of provisioned bandwidth tier."
    return False, None


def check_AZFO_021(r):
    if r.get("type") not in ("Microsoft.ContainerRegistry/registries", "Microsoft.OperationalInsights/workspaces"):
        return None
    activity = get_metric(r, "activity_events_30d")
    if activity is None:
        return None
    if activity == 0:
        return True, "No activity/ingestion events in the last 30 days."
    return False, None


def check_AZFO_022(r):
    if r.get("type") != "Microsoft.OperationalInsights/workspaces":
        return None
    ingestion = get_metric(r, "avg_daily_ingestion_gb_30d")
    tier = get_prop(r, "pricing_tier")
    if ingestion is None or tier is None:
        return None
    if ingestion >= 100 and tier == "PerGB2018":
        return True, f"Sustained {ingestion} GB/day ingestion on Pay-As-You-Go pricing tier."
    return False, None


def check_AZFO_023(r):
    if r.get("type") != "Microsoft.Network/bastionHosts":
        return None
    sessions = get_metric(r, "session_count_30d")
    if sessions is None:
        return None
    if sessions == 0:
        return True, "Zero Bastion sessions in the last 30 days."
    return False, None


def check_AZFO_025(r):
    if r.get("type") != "Microsoft.Compute/virtualMachineScaleSets":
        return None
    autoscale = get_prop(r, "autoscale_profile_configured")
    cpu_std_dev = get_metric(r, "cpu_std_dev_14d")
    if autoscale is None or cpu_std_dev is None:
        return None
    if not autoscale and cpu_std_dev > 15:
        return True, f"No autoscale profile with CPU std-dev of {cpu_std_dev} over 14 days (variable load)."
    return False, None


def check_AZFO_028(r):
    if r.get("type") != "Microsoft.OperationalInsights/workspaces":
        return None
    retention = get_prop(r, "retention_in_days")
    daily_quota = get_prop(r, "daily_quota_gb")
    if retention is None and "daily_quota_gb" not in (r.get("properties") or {}):
        return None  # inventory lacks workspace cost-control fields
    issues = []
    if retention is not None and retention > 90:
        issues.append(f"interactive retention is {retention} days (>90)")
    if daily_quota is None:
        issues.append("no daily ingestion cap configured")
    if issues:
        return True, "Workspace cost controls: " + " and ".join(issues) + "."
    return False, None


RULE_CHECKS = {
    "AZFO-001": check_AZFO_001,
    "AZFO-002": check_AZFO_002,
    "AZFO-003": check_AZFO_003,
    "AZFO-004": check_AZFO_004,
    "AZFO-005": check_AZFO_005,
    "AZFO-006": check_AZFO_006,
    "AZFO-007": check_AZFO_007,
    "AZFO-009": check_AZFO_009,
    "AZFO-010": check_AZFO_010,
    "AZFO-011": check_AZFO_011,
    "AZFO-012": check_AZFO_012,
    "AZFO-013": check_AZFO_013,
    "AZFO-014": check_AZFO_014,
    "AZFO-015": check_AZFO_015,
    "AZFO-016": check_AZFO_016,
    "AZFO-020": check_AZFO_020,
    "AZFO-021": check_AZFO_021,
    "AZFO-022": check_AZFO_022,
    "AZFO-023": check_AZFO_023,
    "AZFO-025": check_AZFO_025,
    "AZFO-028": check_AZFO_028,
}
# Rules AZFO-008, 017, 018, 019, 024, 026, 027 require account/subscription-
# scope data (load balancer telemetry, budgets, Advisor feed, subscription
# offer type, export/FOCUS configuration, FinOps-hub presence) rather than a
# single resource record. They are reported as "not evaluated - requires
# additional data" unless supplied via --extra-findings (the collectors and
# the agent's FinOps-hub checks produce those). See references/finops_rules.json
# for their detection_logic and remediation guidance.


def evaluate(inventory, rules_by_id):
    resources = inventory["resources"] if isinstance(inventory, dict) else inventory
    findings = []
    evaluated_rule_ids = set()

    for resource in resources:
        for rule_id, check_fn in RULE_CHECKS.items():
            result = check_fn(resource)
            if result is None:
                continue
            evaluated_rule_ids.add(rule_id)
            matched, detail = result
            if matched:
                rule = rules_by_id[rule_id]
                findings.append({
                    "rule_id": rule_id,
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "category": rule["category"],
                    "domain": rule["domain"],
                    "resource_id": resource.get("id"),
                    "resource_name": resource.get("name"),
                    "resource_type": resource.get("type"),
                    "resource_group": resource.get("resourceGroup"),
                    "location": resource.get("location"),
                    "finding_detail": detail,
                    "remediation": rule["remediation"],
                    "estimated_savings": rule["estimated_savings"],
                    "monthly_cost_usd": resource.get("monthly_cost_usd"),
                })

    not_evaluated = [
        rid for rid in rules_by_id
        if rid not in RULE_CHECKS and rid not in evaluated_rule_ids
    ]
    return findings, sorted(evaluated_rule_ids), not_evaluated


def main():
    parser = argparse.ArgumentParser(description="Validate an Azure resource inventory against FinOps rules.")
    parser.add_argument("--input", required=True, help="Path to resource inventory JSON")
    parser.add_argument("--rules", default="references/finops_rules.json", help="Path to rule catalog JSON")
    parser.add_argument("--output", default="findings.json", help="Path to write findings JSON")
    parser.add_argument(
        "--extra-findings", action="append", default=[],
        help="Path to a JSON list of pre-built findings (e.g. from "
             "collect_advisor_and_governance.py) to merge in verbatim. Can be "
             "passed multiple times."
    )
    args = parser.parse_args()

    inventory = load_json(args.input)
    ruleset = load_json(args.rules)
    rules_by_id = {r["rule_id"]: r for r in ruleset["rules"]}

    findings, evaluated_rule_ids, not_evaluated = evaluate(inventory, rules_by_id)
    evaluated_rule_ids = set(evaluated_rule_ids)

    for path in args.extra_findings:
        extra = load_json(path)
        for f in extra:
            if f["rule_id"] not in rules_by_id:
                continue  # ignore findings for unknown rule ids rather than crash
            findings.append(f)
            evaluated_rule_ids.add(f["rule_id"])
    evaluated_rule_ids = sorted(evaluated_rule_ids)
    not_evaluated = [rid for rid in not_evaluated if rid not in evaluated_rule_ids]

    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9), f["rule_id"]))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ruleset_version": ruleset.get("ruleset_version"),
        "resource_count": len(inventory["resources"] if isinstance(inventory, dict) else inventory),
        "finding_count": len(findings),
        "findings_by_severity": {
            sev: len([f for f in findings if f["severity"] == sev])
            for sev in ("High", "Medium", "Low")
        },
        "rules_evaluated": evaluated_rule_ids,
        "rules_not_evaluated_needs_data": not_evaluated,
        "findings": findings,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluated {len(evaluated_rule_ids)} rules against {output['resource_count']} resources.")
    print(f"Findings: {output['finding_count']} "
          f"(High: {output['findings_by_severity']['High']}, "
          f"Medium: {output['findings_by_severity']['Medium']}, "
          f"Low: {output['findings_by_severity']['Low']})")
    if not_evaluated:
        print(f"Note: {len(not_evaluated)} rule(s) need account/subscription-scope data not present "
              f"in this inventory: {', '.join(not_evaluated)}")
    print(f"Findings written to {args.output}")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - Live Data Collector
----------------------------------------------------------------
Builds a resource_inventory.json (the schema validate_resources.py expects)
directly from a live Azure subscription, using the Azure CLI. Designed to run
inside an Azure SRE agent environment that is already authenticated (managed
identity, service principal, or interactive `az login`) and has network
access to Azure's management plane.

Minimum RBAC on the target subscription: Reader, Monitoring Reader, and
Cost Management Reader (Cost Management Reader is optional — cost figures
are best-effort and the rest of the collector still works without it).

Usage:
    python3 collect_azure_data.py \
        --subscription-id <sub-id> \
        --output resource_inventory.json \
        --lookback-days 30

    # Restrict to specific resource groups (comma-separated) if the agent's
    # scope should be narrower than the whole subscription:
    python3 collect_azure_data.py --subscription-id <sub-id> \
        --resource-groups rg-prod,rg-data --output resource_inventory.json

Notes on best-effort fields:
    A handful of properties needed by the rule catalog aren't exposed
    cleanly by Resource Graph/Monitor and require extra, sometimes slow,
    lookups (autoscale profiles, DevTest auto-shutdown schedules, storage
    lifecycle policies, reservation coverage). These are fetched with
    individual try/except blocks so a single failure never aborts the run —
    worst case, the corresponding rule is skipped for that resource (which
    validate_resources.py already handles gracefully).
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

RESOURCE_TYPES = [
    "microsoft.compute/virtualmachines",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.compute/disks",
    "microsoft.compute/snapshots",
    "microsoft.network/publicipaddresses",
    "microsoft.network/loadbalancers",
    "microsoft.network/applicationgateways",
    "microsoft.network/bastionhosts",
    "microsoft.network/expressroutecircuits",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.storage/storageaccounts",
    "microsoft.web/serverfarms",
    "microsoft.containerservice/managedclusters",
    "microsoft.containerregistry/registries",
    "microsoft.sql/servers/databases",
    "microsoft.documentdb/databaseaccounts",
    "microsoft.operationalinsights/workspaces",
]

GRAPH_QUERY = f"""
Resources
| where type in ({','.join('"' + t + '"' for t in RESOURCE_TYPES)})
| project id, name, type, resourceGroup, location, tags, sku, properties, subscriptionId
"""


def run_az(args, timeout=120):
    """Run an az CLI command and return parsed JSON. Raises on failure."""
    result = subprocess.run(
        ["az"] + args + ["-o", "json"],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500])
    return json.loads(result.stdout) if result.stdout.strip() else None


def warn(msg):
    print(f"  [warn] {msg}", file=sys.stderr)


def check_az_login(subscription_id):
    try:
        account = run_az(["account", "show"])
    except Exception as e:
        print("ERROR: Azure CLI is not logged in. Run `az login` (or ensure the "
              "agent's managed identity / service principal is configured) and "
              f"retry.\nDetail: {e}", file=sys.stderr)
        sys.exit(1)
    if subscription_id and account.get("id") != subscription_id:
        try:
            run_az(["account", "set", "--subscription", subscription_id])
        except Exception as e:
            print(f"ERROR: could not switch to subscription {subscription_id}: {e}", file=sys.stderr)
            sys.exit(1)
    return run_az(["account", "show"])


def graph_query_all(subscription_id, resource_groups=None):
    """Paginate through Azure Resource Graph results."""
    query = GRAPH_QUERY
    if resource_groups:
        rg_list = ",".join(f'"{rg.lower()}"' for rg in resource_groups)
        query += f'\n| where tolower(resourceGroup) in ({rg_list})'

    resources, skip = [], 0
    while True:
        args = ["graph", "query", "-q", query, "--first", "1000"]
        if subscription_id:
            args += ["--subscriptions", subscription_id]
        if skip:
            args += ["--skip", str(skip)]
        page = run_az(args)
        rows = page.get("data", []) if isinstance(page, dict) else page
        if not rows:
            break
        resources.extend(rows)
        if len(rows) < 1000:
            break
        skip += 1000
    return resources


def get_monthly_cost_by_resource(subscription_id, resource_groups=None):
    """Best-effort Cost Management query for last-30-day actual cost per resource."""
    scope = f"/subscriptions/{subscription_id}"
    body = {
        "type": "ActualCost",
        "timeframe": "MonthToDate",
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        },
    }
    try:
        result = subprocess.run(
            ["az", "rest", "--method", "post",
             "--url", f"https://management.azure.com{scope}/providers/Microsoft.CostManagement/query"
                      f"?api-version=2023-11-01",
             "--body", json.dumps(body), "-o", "json"],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode != 0:
            warn(f"Cost Management query failed (continuing without cost data): {result.stderr.strip()[:200]}")
            return {}
        data = json.loads(result.stdout)
        rows = data.get("properties", {}).get("rows", [])
        cols = [c["name"] for c in data.get("properties", {}).get("columns", [])]
        cost_idx, id_idx = cols.index("Cost"), cols.index("ResourceId")
        return {row[id_idx].lower(): row[cost_idx] for row in rows}
    except Exception as e:
        warn(f"Cost Management query error (continuing without cost data): {e}")
        return {}


def get_metric_avg_max(resource_id, metric_names, lookback_days, aggregation="Average"):
    """Fetch one or more Monitor metrics and return {metric_name: avg} best-effort."""
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        data = run_az([
            "monitor", "metrics", "list",
            "--resource", resource_id,
            "--metric", ",".join(metric_names),
            "--start-time", start,
            "--interval", "P1D",
            "--aggregation", aggregation,
        ], timeout=60)
    except Exception:
        return {}
    out = {}
    for m in (data or {}).get("value", []):
        values = [
            ts.get(aggregation.lower())
            for ts in m.get("timeseries", [{}])[0].get("data", [])
            if ts.get(aggregation.lower()) is not None
        ]
        out[m["name"]["value"]] = values
    return out


def avg_of(values):
    return round(sum(values) / len(values), 2) if values else None


def max_of(values):
    return round(max(values), 2) if values else None


def std_dev_of(values):
    if not values or len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return round(variance ** 0.5, 2)


def populate_metrics(resource, lookback_days):
    rtype = resource["type"].lower()
    rid = resource["id"]
    metrics = {}

    if rtype == "microsoft.compute/virtualmachines":
        cpu = get_metric_avg_max(rid, ["Percentage CPU"], lookback_days)
        cpu_vals = cpu.get("Percentage CPU", [])
        net = get_metric_avg_max(rid, ["Network In Total", "Network Out Total"], lookback_days, "Total")
        net_bytes = sum(sum(v) for v in net.values()) if net else None
        metrics.update({
            "avg_cpu_percent_14d": avg_of(cpu_vals[-14:]),
            "max_cpu_percent_14d": max_of(cpu_vals[-14:]),
            "avg_cpu_percent_30d": avg_of(cpu_vals),
            "network_bytes_30d": net_bytes,
            "power_state": get_power_state(rid),
            "uptime_ratio_30d": estimate_uptime_ratio(cpu_vals),
        })

    elif rtype == "microsoft.compute/virtualmachinescalesets":
        cpu = get_metric_avg_max(rid, ["Percentage CPU"], lookback_days)
        cpu_vals = cpu.get("Percentage CPU", [])
        metrics.update({
            "cpu_std_dev_14d": std_dev_of(cpu_vals[-14:]),
            "uptime_ratio_30d": estimate_uptime_ratio(cpu_vals),
        })

    elif rtype == "microsoft.compute/disks":
        iops = get_metric_avg_max(
            rid, ["Composite Disk Read Operations/sec", "Composite Disk Write Operations/sec"],
            lookback_days
        )
        total_iops_series = [sum(pair) for pair in zip(
            iops.get("Composite Disk Read Operations/sec", []),
            iops.get("Composite Disk Write Operations/sec", [])
        )] if iops else []
        metrics["avg_iops_30d"] = avg_of(total_iops_series)

    elif rtype == "microsoft.web/serverfarms":
        cpu = get_metric_avg_max(rid, ["CpuPercentage"], lookback_days)
        metrics["avg_cpu_percent_14d"] = avg_of(cpu.get("CpuPercentage", [])[-14:])

    elif rtype == "microsoft.containerservice/managedclusters":
        util = get_metric_avg_max(rid, ["node_cpu_usage_percentage"], lookback_days)
        vals = util.get("node_cpu_usage_percentage", [])
        if vals:
            metrics["avg_node_cpu_requests_utilization_14d"] = avg_of(vals[-14:])

    elif rtype == "microsoft.sql/servers/databases":
        util = get_metric_avg_max(rid, ["dtu_consumption_percent"], lookback_days)
        vals = util.get("dtu_consumption_percent", [])
        if not vals:
            util = get_metric_avg_max(rid, ["cpu_percent"], lookback_days)
            vals = util.get("cpu_percent", [])
        if vals:
            metrics["avg_dtu_or_ru_utilization_percent_14d"] = avg_of(vals[-14:])

    elif rtype == "microsoft.documentdb/databaseaccounts":
        util = get_metric_avg_max(rid, ["NormalizedRUConsumption"], lookback_days)
        vals = util.get("NormalizedRUConsumption", [])
        if vals:
            metrics["avg_dtu_or_ru_utilization_percent_14d"] = avg_of(vals[-14:])

    elif rtype == "microsoft.network/bastionhosts":
        sessions = get_metric_avg_max(rid, ["Sessions"], lookback_days, "Total")
        vals = sessions.get("Sessions", [])
        metrics["session_count_30d"] = round(sum(vals)) if vals else 0

    elif rtype in ("microsoft.containerregistry/registries", "microsoft.operationalinsights/workspaces"):
        pull_metric = "SuccessfulPullCount" if "containerregistry" in rtype else "Heartbeat"
        activity = get_metric_avg_max(rid, [pull_metric], lookback_days, "Total")
        vals = activity.get(pull_metric, [])
        metrics["activity_events_30d"] = round(sum(vals)) if vals else 0
        if "operationalinsights" in rtype:
            ingestion = get_metric_avg_max(rid, ["Billable Data Volume"], lookback_days, "Total")
            ivals = ingestion.get("Billable Data Volume", [])
            if ivals:
                # bytes -> GB/day average
                metrics["avg_daily_ingestion_gb_30d"] = round((sum(ivals) / len(ivals)) / (1024 ** 3), 2)

    elif rtype in ("microsoft.network/expressroutecircuits", "microsoft.network/virtualnetworkgateways"):
        metric_name = "BitsInPerSecond" if "expressroute" in rtype else "TunnelAverageBandwidth"
        bw = get_metric_avg_max(rid, [metric_name], lookback_days, "Maximum")
        vals = bw.get(metric_name, [])
        if vals:
            metrics["peak_utilization_percent_30d"] = None  # needs provisioned tier to normalize; left for manual calc

    return metrics


def get_power_state(resource_id):
    try:
        data = run_az(["vm", "get-instance-view", "--ids", resource_id])
        for status in data.get("instanceView", {}).get("statuses", []):
            if status.get("code", "").startswith("PowerState/"):
                return status["code"].split("/")[-1]
    except Exception:
        pass
    return None


def estimate_uptime_ratio(cpu_vals):
    """Rough proxy: fraction of sampled days with a non-null CPU reading."""
    if not cpu_vals:
        return None
    return round(len([v for v in cpu_vals if v is not None]) / max(len(cpu_vals), 1), 2)


def populate_properties(resource, autoscale_index, schedule_index):
    rtype = resource["type"].lower()
    props = resource.get("properties") or {}
    rg = resource.get("resourceGroup", "")
    name = resource.get("name", "")
    out = {}

    if rtype == "microsoft.compute/virtualmachines":
        out["licenseType"] = props.get("licenseType", "None")
        os_type = ((props.get("storageProfile") or {}).get("osDisk") or {}).get("osType")
        out["osType"] = os_type
        out["auto_shutdown_configured"] = f"shutdown-computevm-{name}".lower() in schedule_index.get(rg.lower(), set())
        # eligible_licenses_available and reservation coverage cannot be derived
        # automatically — set by the agent/user via --assume-hybrid-benefit-eligible
        # or left None (rule AZFO-004/003 skipped for this resource until known).

    elif rtype == "microsoft.compute/virtualmachinescalesets":
        out["autoscale_profile_configured"] = resource["id"].lower() in autoscale_index
        out["pricing_model"] = "payg"

    elif rtype == "microsoft.compute/disks":
        out["diskState"] = props.get("diskState")
        out["provisioned_iops"] = props.get("diskIOPSReadWrite")
        # days_unattached: Resource Graph doesn't expose a detach timestamp.
        # If unattached, flag conservatively so it surfaces for manual review;
        # refine with an Activity Log lookup if precise duration is required.
        if props.get("diskState") == "Unattached":
            out["days_unattached"] = 8

    elif rtype == "microsoft.compute/snapshots":
        created = props.get("timeCreated")
        if created:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            out["age_days"] = age

    elif rtype == "microsoft.network/publicipaddresses":
        out["ipConfiguration"] = (props.get("ipConfiguration") or {}).get("id")

    elif rtype == "microsoft.storage/storageaccounts":
        try:
            policy = run_az([
                "storage", "account", "management-policy", "show",
                "--account-name", name, "--resource-group", rg,
            ])
            out["lifecycle_policy_configured"] = bool(policy and policy.get("policy"))
        except Exception:
            out["lifecycle_policy_configured"] = None  # az returns non-zero if none configured
        out["hot_tier_bytes_not_accessed_30d"] = None  # requires Storage Insights / blob inventory; left for manual fill

    elif rtype == "microsoft.web/serverfarms":
        sku = resource.get("sku") or {}
        out["instance_count"] = sku.get("capacity")
        out["autoscale_configured"] = resource["id"].lower() in autoscale_index

    elif rtype == "microsoft.containerservice/managedclusters":
        pools = props.get("agentPoolProfiles") or []
        out["autoscaling_enabled"] = any(p.get("enableAutoScaling") for p in pools)

    elif rtype in ("microsoft.sql/servers/databases", "microsoft.sqlvirtualmachine/sqlvirtualmachines"):
        out["licenseType"] = props.get("licenseType", "LicenseIncluded")
        out["osType"] = "SQLServer"

    elif rtype == "microsoft.operationalinsights/workspaces":
        sku = resource.get("sku") or {}
        out["pricing_tier"] = sku.get("name")

    return out


def build_autoscale_index(subscription_id, resource_groups):
    """Map resource IDs (lowercased) that have an autoscale setting targeting them."""
    index = set()
    try:
        settings = run_az(["monitor", "autoscale", "list", "--subscription", subscription_id]) or []
        for s in settings:
            target = (s.get("targetResourceUri") or "").lower()
            if target:
                index.add(target)
    except Exception as e:
        warn(f"Could not list autoscale settings (continuing): {e}")
    return index


def build_schedule_index(subscription_id):
    """Map resource-group (lowercased) -> set of DevTest auto-shutdown schedule names present."""
    index = {}
    try:
        schedules = run_az([
            "resource", "list", "--resource-type", "microsoft.devtestlab/schedules",
            "--subscription", subscription_id,
        ]) or []
        for s in schedules:
            rg = s.get("resourceGroup", "").lower()
            index.setdefault(rg, set()).add(s.get("name", "").lower())
    except Exception as e:
        warn(f"Could not list auto-shutdown schedules (continuing): {e}")
    return index


def main():
    parser = argparse.ArgumentParser(description="Collect a live Azure resource inventory for FinOps validation.")
    parser.add_argument("--subscription-id", required=True, help="Azure subscription ID to scan")
    parser.add_argument("--resource-groups", help="Comma-separated resource group names to restrict scope to")
    parser.add_argument("--lookback-days", type=int, default=30, help="Metric lookback window in days")
    parser.add_argument("--output", default="resource_inventory.json", help="Path to write the resource inventory JSON")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip Monitor metrics calls (much faster, structural checks only)")
    parser.add_argument("--skip-cost", action="store_true", help="Skip the Cost Management query")
    args = parser.parse_args()

    account = check_az_login(args.subscription_id)
    print(f"Authenticated to subscription: {account.get('name')} ({account.get('id')})")

    rg_filter = [rg.strip() for rg in args.resource_groups.split(",")] if args.resource_groups else None

    print("Querying Azure Resource Graph...")
    raw_resources = graph_query_all(args.subscription_id, rg_filter)
    print(f"  found {len(raw_resources)} resources across {len(RESOURCE_TYPES)} tracked types")

    cost_by_id = {} if args.skip_cost else get_monthly_cost_by_resource(args.subscription_id, rg_filter)

    print("Indexing autoscale settings and auto-shutdown schedules...")
    autoscale_index = build_autoscale_index(args.subscription_id, rg_filter)
    schedule_index = build_schedule_index(args.subscription_id)

    resources = []
    for i, r in enumerate(raw_resources, start=1):
        print(f"  [{i}/{len(raw_resources)}] {r.get('type')}: {r.get('name')}", file=sys.stderr)
        entry = {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "resourceGroup": r.get("resourceGroup"),
            "location": r.get("location"),
            "tags": r.get("tags") or {},
            "sku": (r.get("sku") or {}).get("name"),
            "monthly_cost_usd": cost_by_id.get(r["id"].lower()),
        }
        entry["properties"] = populate_properties(r, autoscale_index, schedule_index)
        if not args.skip_metrics:
            try:
                entry["metrics"] = populate_metrics(r, args.lookback_days)
            except Exception as e:
                warn(f"metrics collection failed for {r['name']}: {e}")
                entry["metrics"] = {}
        resources.append(entry)

    with open(args.output, "w") as f:
        json.dump({"resources": resources, "collected_at": datetime.now(timezone.utc).isoformat(),
                    "subscription_id": args.subscription_id}, f, indent=2)

    print(f"\nWrote {len(resources)} resources to {args.output}")
    print("Some rule inputs (e.g. Hybrid Benefit eligibility, reservation coverage, "
          "storage hot-tier cold-data volume, unattached-disk duration) are best-effort "
          "or left null where Azure has no direct API for them — review "
          "references/azure-data-collection.md for how to backfill those manually if needed.")


if __name__ == "__main__":
    sys.exit(main())

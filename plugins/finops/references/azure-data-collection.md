# Collecting Azure Resource Data for FinOps Validation

If the agent has an authenticated `az` CLI session with network access to Azure (the
normal case for an Azure SRE agent), prefer running
**`scripts/collect_azure_data.py`** and **`scripts/collect_advisor_and_governance.py`**
directly (or the single-command **`scripts/run_finops_validation.py`** orchestrator) —
see the "Mode A — Live" workflow in `SKILL.md`. Those scripts wrap the `az` commands
below automatically and shape the output into the schema `validate_resources.py`
expects.

This document is for two other situations:
1. **Understanding/debugging** what the live collector scripts are doing under the hood.
2. **Manual fallback** — the agent has no Azure network access in its current
   environment (e.g. a sandboxed build/preview session), so the person needs to run
   these commands themselves elsewhere and upload the resulting JSON ("Mode B" in
   `SKILL.md`).

Below are the underlying data sources, ordered from richest to simplest.

## Required RBAC

| Data source | Minimum role | Required? |
|---|---|---|
| Resource Graph, resource properties, tags, SKUs | `Reader` (subscription scope) | Yes |
| Azure Monitor metrics (CPU, IOPS, sessions, ingestion, etc.) | `Monitoring Reader` | Yes, for utilization-based rules |
| Cost Management query, budgets | `Cost Management Reader` | Optional — cost figures/AZFO-017 are skipped without it |
| Azure Advisor recommendations | `Reader` (Advisor uses the same RBAC) | Yes, for AZFO-018 |

`az login` (interactive), a service principal (`az login --service-principal`), or a
system/user-assigned managed identity all work — `collect_azure_data.py` just calls
`az account show` to confirm a session exists before doing anything else.

## Option A — Azure Resource Graph (recommended)

Resource Graph gives a single, fast, tenant-wide query surface and can include tags,
SKU, and properties in one call.

```bash
az graph query -q "
Resources
| project id, name, type, location, resourceGroup, subscriptionId, tags, sku, properties
" --first 1000 -o json > resource_inventory_raw.json
```

Utilization metrics (CPU, IOPS, throughput, session counts, etc.) are not in Resource
Graph — pull those separately with Azure Monitor Metrics and merge them in, or use
Azure Advisor (below) which has already done this analysis for compute/storage.

## Option B — Azure Advisor cost recommendations (fastest signal for AZFO-001/002/003/006/013/014)

```bash
az advisor recommendation list --category Cost -o json > advisor_cost_recs.json
```

Advisor recommendations map closely to several rules in `finops_rules.json`
(right-sizing, reservations, idle resources). These can be merged directly into
findings with high confidence since Microsoft has already computed the utilization
analysis.

## Option C — Azure Monitor Metrics for utilization-based rules

For rules that need utilization data (AZFO-001, 002, 006, 008, 013, 014, 015, 020, 023,
025), pull per-resource metrics, e.g.:

```bash
az monitor metrics list \
  --resource <resource-id> \
  --metric "Percentage CPU" \
  --interval PT1H \
  --start-time <14-days-ago> \
  -o json
```

## Option D — Cost Management exports (for spend figures / estimated savings)

```bash
az costmanagement export create \
  --name finops-validator-export \
  --scope "/subscriptions/<sub-id>" \
  --definition-type ActualCost \
  --schedule-frequency Daily
```
Cost data lets `generate_report.py` translate percentage-based savings estimates into
approximate dollar figures per finding.

## Expected input schema for `validate_resources.py`

The script expects a JSON array of resource objects. Fields are read defensively (a
missing field just means the rule that needs it is skipped for that resource, not a
crash). Minimum useful shape:

```json
[
  {
    "id": "/subscriptions/xxx/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web01",
    "name": "vm-web01",
    "type": "Microsoft.Compute/virtualMachines",
    "resourceGroup": "rg-prod",
    "location": "eastus",
    "tags": {"Environment": "prod", "CostCenter": "1234", "Owner": "team-web"},
    "sku": "Standard_D4s_v5",
    "monthly_cost_usd": 140.00,
    "metrics": {
      "avg_cpu_percent_14d": 3.2,
      "max_cpu_percent_14d": 11.0,
      "avg_cpu_percent_30d": 3.5,
      "network_bytes_30d": 15000,
      "power_state": "running"
    },
    "properties": {
      "licenseType": "None",
      "osType": "Windows"
    }
  }
]
```

See `examples/sample_resource_inventory.json` for a full worked example covering most
rule categories, and `examples/sample_findings.json` for the corresponding output.

If the user cannot export live data (no Azure CLI access in this environment), offer to
walk them through the `az` commands above so they can run them where they do have
access, then re-upload the resulting JSON for analysis.

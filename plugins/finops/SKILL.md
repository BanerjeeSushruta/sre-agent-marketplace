---
name: azure-finops-validator
description: Validate Azure resources — live against a real subscription via the Azure CLI, or from an uploaded export — against Azure/FinOps Foundation cost-optimization best practices, and produce a PDF remediation report with rule IDs. Use whenever the user (Azure SRE, FinOps analyst, cloud engineer, platform team) asks to audit Azure spend, find cost-saving opportunities, check FinOps compliance, review Advisor cost recommendations, right-size resources, find idle/orphaned/unattached resources, check reserved instance or Hybrid Benefit coverage, or generate a cost-optimization/FinOps assessment report, even without the word "FinOps". Always use this skill (not ad-hoc scripting or one-off az CLI calls) when the agent has Azure CLI/subscription access and is asked to assess cost posture, or when a resource inventory, Resource Graph export, Advisor export, or cost export is provided, or the deliverable is a PDF with remediation guidance and rule IDs.
---

# Azure FinOps Best Practices Validator

An Azure SRE agent skill that evaluates Azure resources against a structured catalog of
FinOps and cost-optimization best practices (rule IDs `AZFO-001`...`AZFO-025`), aligned to:

- The **FinOps Foundation FinOps Framework** (Inform / Optimize / Operate)
- The **Azure Well-Architected Framework — Cost Optimization pillar**
- **Azure Advisor** cost recommendation categories
- **Azure Cost Management + Billing** best practices

Output is a findings dataset and a polished **PDF report** with remediation guidance,
citing the specific rule ID for every finding, suitable for sharing with engineering
leads, FinOps practitioners, or finance stakeholders.

## When to use this skill

Use this skill for requests like:
- "Audit our Azure subscription for cost optimization opportunities"
- "Check our resources against FinOps best practices"
- "Find idle/orphaned/unattached Azure resources"
- "Are we missing Reserved Instance or Hybrid Benefit coverage?"
- "Generate a FinOps remediation report with rule IDs in PDF"
- Any request involving an uploaded Azure resource export (Resource Graph, Advisor,
  Cost Management) that should be checked for cost issues

## Workflow

First determine which mode applies: **does this environment have an Azure-authenticated
`az` CLI with network access to Azure's management plane** (the normal case for an
Azure SRE agent running with a managed identity, service principal, or an already
`az login`'d session)? Check with `az account show`. If yes, use **Mode A (live)**. If
`az` isn't available/authenticated here, fall back to **Mode B (file-based)**.

### Mode A — Live Azure subscription (preferred for an SRE agent with Azure access)

Run the whole pipeline in one command:
```bash
python3 scripts/run_finops_validation.py \
  --subscription-id <sub-id> \
  --title "<subscription or scope name>" \
  --output-dir /mnt/user-data/outputs \
  [--resource-groups rg-prod,rg-data]   # optional: narrow scope
  [--assume-devtest-subscription]        # optional: only if the whole sub is non-prod
```
This chains, in order:
1. `scripts/collect_azure_data.py` — Resource Graph inventory + Monitor metrics + best-effort
   Cost Management figures, written to `resource_inventory.json`.
2. `scripts/collect_advisor_and_governance.py` — Azure Advisor cost recommendations,
   Cost Management budgets, and Dev/Test offer check, written to
   `account_scope_findings.json` (covers rules that need subscription-scope data:
   AZFO-017, AZFO-018, AZFO-019).
3. `scripts/validate_resources.py` — merges both into `findings.json`.
4. `scripts/generate_report.py` — final PDF.

Minimum RBAC on the target subscription: **Reader** + **Monitoring Reader** (required);
**Cost Management Reader** (optional — cost figures are best-effort and the run still
completes without it). If a step fails due to permissions, the collector scripts warn
and continue rather than aborting — mention any such gaps to the user in your summary.

If the run needs to be faster (large subscription, or metrics access is slow), add
`--skip-metrics` for structural-only checks first (tags, orphaned resources, unattached
disks, missing budgets/Advisor/Hybrid-Benefit flags), then a full run later.

You can also run the four scripts individually (see each script's `--help` /
docstring) if you need to inspect or hand-edit intermediate JSON between steps —
useful for scoping to specific resource groups or merging in additional Advisor data.

### Mode B — File-based (no live Azure access from this environment)

- **User already uploaded a JSON/CSV export** (Resource Graph, `az resource list`,
  Advisor, Cost Management) → read it with `view` or pandas, and transform it into the
  schema below if needed.
- **User has Azure CLI access themselves, elsewhere** → point them at
  `scripts/collect_azure_data.py` and `scripts/collect_advisor_and_governance.py` to run
  in their own environment, or give them the underlying `az` commands from
  `references/azure-data-collection.md`, then ask them to upload the resulting JSON.
- **Demo/dry run** → use `examples/sample_resource_inventory.json`.

Target schema (defensive — missing fields simply skip the rules that need them):
```json
{
  "resources": [
    {
      "id": "...", "name": "...", "type": "Microsoft.Compute/virtualMachines",
      "resourceGroup": "...", "location": "...", "tags": {...}, "sku": "...",
      "monthly_cost_usd": 0.0, "metrics": {...}, "properties": {...}
    }
  ]
}
```
Then run steps 3-4 manually:
```bash
python3 scripts/validate_resources.py \
  --input <resource_inventory.json> \
  --rules references/finops_rules.json \
  --output /home/claude/findings.json \
  [--extra-findings account_scope_findings.json]   # if you have one

python3 scripts/generate_report.py \
  --findings /home/claude/findings.json \
  --rules references/finops_rules.json \
  --output /mnt/user-data/outputs/AzureFinOps_Validation_Report.pdf \
  --title "<subscription or scope name the user gave you>"
```
Full field-by-field guidance is in `references/azure-data-collection.md`.

### Either mode — check the console output

Both `validate_resources.py` and the collectors print warnings/notes to the console
(rules skipped for lack of data, Advisor/Cost Management permission errors, etc.) —
read these and mention them to the user rather than silently omitting the gap.

### Present the report

The PDF has a cover page, executive summary (finding counts by severity, monthly cost
on flagged resources), a sortable findings table, per-rule-ID remediation detail
sections, and a full rule-catalog appendix. Present it with `present_files`.

### Summarize in chat

After sharing the PDF, give a short in-chat summary (don't restate the whole report):
counts by severity, the top 2-3 highest-impact findings by rule ID, and any rules that
need more data to evaluate. Offer to re-run once the user provides missing data (e.g.,
budgets/Advisor export) to cover the remaining rules.

## Extending the rule catalog

To add a new rule:
1. Add an entry to `references/finops_rules.json` with a new `AZFO-0NN` ID, `domain`
   (Inform/Optimize/Operate/Manage), `category`, `severity`, `resource_types`,
   `description`, `detection_logic` (plain-language), `remediation`, and
   `estimated_savings`.
2. If the rule can be evaluated from resource-level JSON, add a matching
   `check_AZFO_0NN(resource)` function in `scripts/validate_resources.py` and register
   it in the `RULE_CHECKS` dict.
3. Rules that need subscription/account-scope data (budgets, Advisor feed, cost
   exports) can stay detection-logic-only — the report's appendix and "not evaluated"
   note in the executive summary will still surface them for manual follow-up.

## Files in this skill

```
azure-finops-validator/
├── SKILL.md
├── references/
│   ├── finops_rules.json                    # machine-readable rule catalog (25 rules, AZFO-001..025)
│   └── azure-data-collection.md             # underlying az commands / manual fallback reference
├── scripts/
│   ├── run_finops_validation.py             # orchestrator: live subscription -> PDF, one command
│   ├── collect_azure_data.py                # live: Resource Graph + Monitor + Cost Mgmt -> resource_inventory.json
│   ├── collect_advisor_and_governance.py    # live: Advisor/budgets/Dev-Test offer -> account_scope_findings.json
│   ├── validate_resources.py                # rules engine: inventory (+ extra findings) -> findings.json
│   └── generate_report.py                   # findings.json -> PDF remediation report
└── examples/
    ├── sample_resource_inventory.json
    ├── sample_findings.json
    └── Sample_AzureFinOps_Validation_Report.pdf
```

## Notes and limitations

- **Live mode (Mode A)** requires the agent's `az` CLI session to already be
  authenticated (managed identity, service principal, or `az login`) with network
  access to `management.azure.com`; this build/demo environment itself has no network
  access, so `collect_azure_data.py` and `collect_advisor_and_governance.py` are
  validated for correctness (compiled, logic-reviewed) but were exercised end-to-end
  only via **Mode B** against `examples/sample_resource_inventory.json`. Run a
  `--skip-metrics` dry run first against a real subscription to confirm connectivity
  and RBAC before a full run.
- A few fields have no direct Azure API and are collected best-effort or left `null`
  (which just means the corresponding rule is skipped for that resource): Hybrid
  Benefit license eligibility, Reserved Instance/Savings Plan coverage, exact
  unattached-disk duration (flagged conservatively instead), and cold-data volume in
  a storage account's hot tier. `references/azure-data-collection.md` explains how to
  backfill these manually or via additional Azure APIs if more precision is needed.
- Estimated savings in the rule catalog are industry-typical ranges (Azure Advisor,
  Well-Architected guidance), not guarantees — actual savings depend on committed-use
  pricing, region, and negotiated rates.
- Severity is a starting heuristic (High = clear waste or high-risk cost exposure,
  Medium = meaningful optimization, Low = governance/hygiene or small $ impact) —
  encourage the user to re-prioritize using their own cost data once `monthly_cost_usd`
  is populated from a real Cost Management export.

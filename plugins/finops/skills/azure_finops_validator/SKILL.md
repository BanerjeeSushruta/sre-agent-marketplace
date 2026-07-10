---
name: azure_finops_validator
description: Validate Azure resources — live against a real subscription via the Azure CLI, or from an uploaded export — against Azure/FinOps Foundation cost-optimization best practices, and produce a PDF remediation report with rule IDs. Use whenever the user (Azure SRE, FinOps analyst, cloud engineer, platform team) asks to audit Azure spend, find cost-saving opportunities, check FinOps compliance, review Advisor cost recommendations, right-size resources, find idle/orphaned/unattached resources, check reserved instance or Hybrid Benefit coverage, assess FOCUS export or FinOps hub adoption, or generate a cost-optimization/FinOps assessment report, even without the word "FinOps". Always use this skill (not ad-hoc scripting or one-off az CLI calls) when the agent has Azure CLI/subscription access and is asked to assess cost posture, or when a resource inventory, Resource Graph export, Advisor export, cost export, or FinOps hub (Data Explorer/Fabric) dataset is provided, or the deliverable is a PDF with remediation guidance and rule IDs.
---

# Azure FinOps Best Practices Validator

An Azure SRE agent skill that evaluates Azure resources against a structured catalog of
FinOps and cost-optimization best practices (rule IDs `AZFO-001`...`AZFO-028`), aligned to:

- The **FinOps Foundation FinOps Framework** (Inform / Optimize / Operate)
- The **Azure Well-Architected Framework — Cost Optimization pillar**
- **Azure Advisor** cost recommendation categories
- **Azure Cost Management + Billing** best practices
- The **Microsoft FinOps toolkit** — FinOps hubs and the **FOCUS** open cost/usage
  specification (see `references/finops-hubs.md`)

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
- "Do we have FOCUS exports / a FinOps hub set up?" or "How should we centralize
  cost reporting across subscriptions/tenants?"
- Any request involving an uploaded Azure resource export (Resource Graph, Advisor,
  Cost Management) that should be checked for cost issues

## Workflow

First determine which mode applies: **does this environment have an Azure-authenticated
`az` CLI with network access to Azure's management plane** (the normal case for an
Azure SRE agent running with a managed identity, service principal, or an already
`az login`'d session)? Check with `az account show`. If yes, use **Mode A (live)**. If
`az` isn't available/authenticated here, fall back to **Mode B (file-based)**.

### Mode A — Live Azure subscription (preferred for an SRE agent with Azure access)

**Always start with the RBAC preflight** and relay its role table to the user
before running the full pipeline — it reports the identity in use, which required
roles (Reader, Monitoring Reader) and optional roles (Cost Management Reader,
Log Analytics Reader) are held or missing, exactly what each gap will skip, and
ready-made `az role assignment create` commands for the gaps:
```bash
python3 scripts/check_permissions.py --subscription-id <sub-id>
```
Exit 1 = not authenticated; exit 2 = Reader missing (stop, ask the user to grant
it); exit 0 = safe to proceed (missing optional roles are warnings). Summarize
the table for the user, then continue — don't silently proceed with gaps.

Install the one Python dependency needed for the PDF step, then run the whole
pipeline in one command (paths are relative to this skill's directory — the
preflight runs again as step 1/5, add `--skip-preflight` if you already ran it):
```bash
pip install reportlab   # only third-party dependency (PDF generation)

python3 scripts/run_finops_validation.py \
  --subscription-id <sub-id> \
  --title "<subscription or scope name>" \
  --output-dir ./finops-output \
  [--resource-groups rg-prod,rg-data]   # optional: narrow scope
  [--assume-devtest-subscription]        # optional: only if the whole sub is non-prod
  [--skip-preflight]                     # optional: preflight already run separately
```
This chains, in order:
1. `scripts/check_permissions.py` — preflight RBAC verification (above); also writes
   `preflight_permissions.json` so the role table is embedded in the final PDF's
   Identity & Access Coverage section.
2. `scripts/collect_azure_data.py` — Resource Graph inventory + Monitor metrics + best-effort
   Cost Management figures, written to `resource_inventory.json`.
3. `scripts/collect_advisor_and_governance.py` — Azure Advisor cost recommendations,
   Azure Reservation purchase recommendations (Consumption API, reported under
   AZFO-003 with SKU/term/quantity/savings detail), Cost Management budgets, and
   Dev/Test offer check, written to `account_scope_findings.json` (covers rules that
   need subscription-scope data: AZFO-003, AZFO-017, AZFO-018, AZFO-019).
4. `scripts/validate_resources.py` — merges both into `findings.json`.
5. `scripts/generate_report.py` — final PDF.

Minimum RBAC on the target subscription: **Reader** + **Monitoring Reader** (required);
**Cost Management Reader** (optional — cost figures are best-effort and the run still
completes without it); **Log Analytics Reader** (optional — deeper per-table log cost
detail). The preflight (step 1) verifies these up front. If a later step fails due to
permissions, the collector scripts warn
and continue rather than aborting — mention any such gaps to the user in your summary.

If the run needs to be faster (large subscription, or metrics access is slow), add
`--skip-metrics` for structural-only checks first (tags, orphaned resources, unattached
disks, missing budgets/Advisor/Hybrid-Benefit flags), then a full run later.

You can also run the five scripts individually (see each script's `--help` /
docstring) if you need to inspect or hand-edit intermediate JSON between steps —
useful for scoping to specific resource groups or merging in additional Advisor data.

#### Mode A extra: FinOps hubs / FOCUS posture (AZFO-026, AZFO-027)

After (or alongside) the pipeline, evaluate the scope's cost-data platform posture
using `references/finops-hubs.md`:

1. **FOCUS export check (AZFO-026)** — `az costmanagement export list` on the
   subscription scope; pass if a scheduled export with the FOCUS dataset exists.
2. **FinOps hub detection (AZFO-027)** — Resource Graph query for the co-deployed
   hub set (Data Factory + Data Lake storage + Key Vault, optionally Data
   Explorer/Fabric RTI, typically named/tagged `finops-hub`). Only raise AZFO-027
   when the engagement genuinely spans multiple subscriptions/tenants and no hub
   or equivalent platform exists.
3. Append any resulting findings to `account_scope_findings.json` (same shape as
   the AZFO-017/018/019 entries) **before** step 4 of the pipeline, or re-run
   `validate_resources.py` with `--extra-findings`, so they appear in the PDF.

If a hub **is** present:
- Prefer its Data Explorer/Fabric `Hub` database (FOCUS-normalized `Costs` table)
  for cost figures — query via KQL and backfill `monthly_cost_usd` in the inventory
  from `EffectiveCost` per `ResourceId` (needs Viewer on the `Hub`/`Ingestion`
  databases). This gives more accurate severity ranking than the best-effort
  Cost Management query.
- Don't flag the hub's own storage/ADX/Data Factory resources as idle/orphaned —
  low steady-state utilization between export runs is normal.
- Apply the hub-hygiene checks in `references/finops-hubs.md` (no edits to
  `msexports` or built-in pipelines, wrapper Bicep module for upgrades) and note
  violations in your summary.

### Mode B — File-based (no live Azure access from this environment)

- **User already uploaded a JSON/CSV export** (Resource Graph, `az resource list`,
  Advisor, Cost Management) → read the file and transform it into the schema below
  if needed.
- **User has Azure CLI access themselves, elsewhere** → point them at
  `scripts/collect_azure_data.py` and `scripts/collect_advisor_and_governance.py` to run
  in their own environment, or give them the underlying `az` commands from
  `references/azure-data-collection.md`, then ask them to upload the resulting JSON.
- **User has a FinOps hub** → the FOCUS parquet/CSV data in the hub's `ingestion`
  container (or a KQL export from the `Hub` database's `Costs` table) is an ideal
  Mode B input: map `ResourceId` → `id`, `EffectiveCost` (summed per resource per
  month) → `monthly_cost_usd`, and `ServiceName`/`ResourceType` → `type`. See
  `references/finops-hubs.md` for the useful FOCUS columns.
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
Then run the validate + report steps manually (from this skill's directory):
```bash
python3 scripts/validate_resources.py \
  --input <resource_inventory.json> \
  --rules references/finops_rules.json \
  --output ./finops-output/findings.json \
  [--extra-findings account_scope_findings.json]   # if you have one

python3 scripts/generate_report.py \
  --findings ./finops-output/findings.json \
  --rules references/finops_rules.json \
  --output ./finops-output/AzureFinOps_Validation_Report.pdf \
  --title "<subscription or scope name the user gave you>"
```
Full field-by-field guidance is in `references/azure-data-collection.md`.

### Either mode — check the console output

Both `validate_resources.py` and the collectors print warnings/notes to the console
(rules skipped for lack of data, Advisor/Cost Management permission errors, etc.) —
read these and mention them to the user rather than silently omitting the gap.

### Present the report

The pipeline produces **exactly one deliverable: a single PDF** (the JSON files in
the output directory are intermediate working data, not reports). The PDF contains,
in order: a cover page; an executive summary (finding counts by severity, monthly
cost on flagged resources); an **Identity & Access Coverage** section (the preflight
role table — which required/optional roles the assessment ran with and what any gap
skipped); a **Cost-Saving Opportunities by
Category** table (findings, flagged monthly cost, and typical savings potential per
category); the sortable findings table; an **Azure Reservation & Savings Plan
Opportunities** section (per-SKU purchase recommendations with term/quantity/savings
and purchase guidance); a **Log & Monitoring Cost Analysis** section (Log Analytics
findings plus the KQL deep-dive query for top ingestion drivers); per-rule-ID
remediation detail sections; a **Cost-Saving Guardrails — Azure Policy Suggestions**
section (built-in/custom policy assignments that prevent recurrence, with the ones
related to fired rules flagged "recommended now"); and the full rule-catalog
appendix. Share the generated PDF file with the user (attach it to the
conversation/incident, or tell them its output path).

### Summarize in chat

After sharing the PDF, give a short in-chat summary (don't restate the whole report):
counts by severity, the top 2-3 highest-impact findings by rule ID, and any rules that
need more data to evaluate. Offer to re-run once the user provides missing data (e.g.,
budgets/Advisor export) to cover the remaining rules. If AZFO-026/027 fired, offer the
FinOps hubs deployment walkthrough from `references/finops-hubs.md` (resource-provider
registration, networking plan, template deploy, FOCUS exports, required roles) as the
structural fix that also improves every future run of this skill.

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
skills/azure_finops_validator/
├── SKILL.md
├── references/
│   ├── finops_rules.json                    # machine-readable rule catalog (28 rules, AZFO-001..028)
│   ├── azure-data-collection.md             # underlying az commands / manual fallback reference
│   ├── azure-policy-guardrails.json         # cost guardrails: Azure Policy suggestions rendered in the report
│   └── finops-hubs.md                       # FinOps hubs / FOCUS: detection, KQL usage, deployment guidance
├── scripts/
│   ├── run_finops_validation.py             # orchestrator: preflight + live subscription -> PDF, one command
│   ├── check_permissions.py                 # preflight: verify identity + required RBAC roles, print gap table
│   ├── collect_azure_data.py                # live: Resource Graph + Monitor + Cost Mgmt -> resource_inventory.json
│   ├── collect_advisor_and_governance.py    # live: Advisor/reservations/budgets/Dev-Test -> account_scope_findings.json
│   ├── validate_resources.py                # rules engine: inventory (+ extra findings) -> findings.json
│   └── generate_report.py                   # findings.json -> PDF remediation report
└── examples/
    ├── sample_resource_inventory.json
    ├── sample_findings.json
    └── Sample_AzureFinOps_Validation_Report.pdf
```

## Notes and limitations

- **Live mode (Mode A)** requires the agent's `az` CLI session to already be
  authenticated (for Azure SRE Agent this is the agent's managed identity; otherwise
  a service principal or `az login`) with network access to `management.azure.com`.
  Run a `--skip-metrics` dry run first against a real subscription to confirm
  connectivity and RBAC before a full run.
- `generate_report.py` needs the `reportlab` package (`pip install reportlab`);
  everything else is Python standard library + the `az` CLI.
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
  is populated from a real Cost Management export or a FinOps hub's FOCUS dataset.
- AZFO-026/027 are evaluated by the agent directly (per `references/finops-hubs.md`),
  not by `validate_resources.py` — they need subscription/estate context (export
  configuration, multi-tenant scope) that resource-level JSON doesn't carry. Feed the
  results in via `--extra-findings` so they land in the PDF.

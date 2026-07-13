---
name: azure_governance
description: Review Azure governance posture and provide prioritized, actionable improvement insights for three scopes — Azure platform (tenant/management groups), landing zone, or standalone subscription. Assesses policy compliance, RBAC and identity, management group hierarchy, tagging standards, cost optimization (Advisor), quotas, resource health, monitoring/diagnostics coverage, and security baseline, aligned to the Cloud Adoption Framework (CAF) governance disciplines and Azure Landing Zone design areas. Uses the azure-mcp-governance MCP connector (open-source Azure MCP Server, read-only) with az CLI fallback, and delivers a scored findings report with a remediation roadmap. Use when asked to review governance, audit a landing zone, assess a subscription, check policy compliance, review RBAC sprawl, or produce a governance improvement plan.
---

# Azure Governance Review — Platform, Landing Zone & Subscription

Assess governance posture at a user-selected scope and deliver **actionable,
prioritized insights** aligned to the Cloud Adoption Framework (CAF) governance
disciplines and Azure Landing Zone (ALZ) design areas.

**MCP connector:** `azure-mcp-governance` — the open-source
[Azure MCP Server](https://github.com/microsoft/mcp) running **read-only** and
scoped to governance namespaces (`policy`, `role`, `advisor`, `quota`,
`resourcehealth`, `group`, `subscription`, `monitor`, `extension`). It runs as
a stdio command in the agent sandbox — nothing to host. If the connector is
unavailable, every check below has an `az` CLI fallback.

## Inputs to collect from the user

1. **Scope** (one of):
   - **Platform** — whole tenant: management group hierarchy + all subscriptions
   - **Landing zone** — a management group or a set of workload subscriptions
   - **Standalone subscription** — a single subscription ID/name
2. **Optional**: compliance framework emphasis (CIS/NIST/ISO), cost focus,
   report depth (executive summary vs full), output format (chat/markdown/PDF).

## Assessment areas (run all; skip N/A for the chosen scope)

### 1. Resource organization (ALZ design area)
- Management group hierarchy depth/shape; orphaned or flat structures
  (platform scope): `az account management-group list -o json`
- Subscription placement vs purpose (platform/connectivity/identity/workload)
- Resource group sprawl and empty RGs:
  `az graph query -q "ResourceContainers | where type =~ 'microsoft.resources/subscriptions/resourcegroups' | join kind=leftouter (Resources | summarize c=count() by resourceGroup, subscriptionId) on resourceGroup | where isnull(c)"`

### 2. Azure Policy & compliance
- MCP: policy assignment list + compliance state; or
  `az policy state summarize` / `az policy assignment list --disable-scope-strict-match`
- Flag: scopes with **no policy assignments**, missing ALZ baseline policies
  (allowed locations, require tags, deny public IP where applicable, audit
  diagnostic settings), high non-compliance rates, assignments in
  DoNotEnforce mode that never graduated.

### 3. Identity & access (RBAC)
- MCP: role assignment list; or `az role assignment list --all -o json`
- Flag: Owner/Contributor at subscription or MG scope for **users** (should be
  groups/PIM), guest accounts with privileged roles, stale service principal
  assignments, custom roles duplicating built-ins, assignment count near the
  limit (~4,000/subscription), classic administrators.

### 4. Tagging & naming standards
- `az graph query -q "Resources | where isnull(tags) or tags == '{}' | summarize count() by type, subscriptionId"`
- Measure tag coverage for common governance tags (owner, env,
  cost-center); flag inconsistent casing/synonyms (env vs environment).
  Recommend tag policy (inherit-from-RG + require-on-RG pattern), not
  per-resource deny.

### 5. Cost optimization
- MCP: `advisor` recommendations (Cost category); or
  `az advisor recommendation list --category Cost -o json`
- Flag: idle/underutilized resources, missing reservations/savings plans
  signals, orphaned disks/IPs/NICs:
  `az graph query -q "Resources | where type =~ 'microsoft.compute/disks' and properties.diskState =~ 'Unattached'"`

### 6. Resiliency & service health
- MCP: `resourcehealth` events + availability; Advisor HighAvailability category
- Flag: single-instance production VMs, missing zone redundancy on flagged
  services, unacknowledged service health advisories.

### 7. Monitoring & diagnostics coverage
- Diagnostic settings coverage on key types (Key Vault, NSG, SQL, Storage,
  AKS): `az monitor diagnostic-settings list --resource <id>` sampled via
  Resource Graph; activity log export to Log Analytics; presence of action
  groups/alerts on platform events.

### 8. Security baseline
- Defender for Cloud plan status: `az security pricing list -o json`
- Secure score if available: `az security secure-scores list`
- Flag: Defender plans off for hosted workload types, missing security
  contacts (`az security contact list`), subscriptions without MFA-enforcing
  policy signals.

### 9. Quotas & scale headroom
- MCP: `quota` usage; flag any usage > 80% of limit in active regions.

### 10. Compliance report (optional, thorough runs)
- MCP `extension` namespace exposes **azqr** (Azure Quick Review) for a
  rule-based compliance scan; or run `azqr scan -s <SUB_ID>` if the CLI is
  available in the sandbox.

## Scoring & prioritization

Rate each area **Green / Amber / Red** with a one-line justification. Then
build the insight list; every insight must have:

| Field | Rule |
| --- | --- |
| Severity | Critical / High / Medium / Low |
| Finding | What was observed, with counts and example resource IDs |
| Impact | Risk or cost consequence in business terms |
| Action | Concrete fix — exact `az` command, policy definition to assign, or portal path |
| Effort | Quick win (<1 day) / Project (sprint) / Program (quarter) |

Order the roadmap: **Critical security/identity → policy guardrails →
quick-win cost savings → monitoring gaps → structural improvements.**

## Deliverable

1. **Executive summary** — scope, overall posture score (0–100 weighted
   across the 10 areas), top 5 insights.
2. **Scorecard table** — area, RAG status, key metric.
3. **Findings & actions** — per area, using the insight format above.
4. **Remediation roadmap** — sequenced quick wins → projects → programs.
5. On request, export as markdown or PDF (reuse the HTML→PDF conversion
   chain from the azure-architecture plugin if installed).

## Guardrails

- **Read-only.** Never remediate in the same run; output commands for the
  user to review. The MCP server is started with `--read-only`.
- Requires **Reader** at the assessment scope; policy insights benefit from
  **Resource Policy Reader**; security checks need **Security Reader**.
  Report any permission-denied areas as "Not assessed" rather than guessing.
- For platform scope with many subscriptions, sample the largest 10 by
  resource count and state the sampling in the report.

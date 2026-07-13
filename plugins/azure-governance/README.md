# Azure Governance Plugin

Reviews Azure governance posture at **platform** (tenant/management groups),
**landing zone**, or **standalone subscription** scope and delivers prioritized,
actionable insights: policy compliance, RBAC, tagging, cost optimization,
resiliency, monitoring coverage, security baseline, and quota headroom —
aligned to Cloud Adoption Framework governance disciplines and Azure Landing
Zone design areas.

## What it installs

| Component | Name | Purpose |
| --- | --- | --- |
| Skill | `azure_governance` | 10-area governance assessment runbook with scored report and remediation roadmap |
| MCP server | `azure-mcp-governance` | Open-source [Azure MCP Server](https://github.com/microsoft/mcp) (MIT), read-only, governance namespaces only |

## No hosting required

The MCP server runs as a **stdio command inside the agent sandbox** via
`npx -y @azure/mcp@latest server start` — there is no endpoint to deploy or
maintain. It is locked down at startup:

- `--read-only` — write tools are never exposed
- `--namespace policy role advisor quota resourcehealth group subscription monitor extension`
  — only governance-relevant tools are loaded

Authentication uses the Azure credential chain available in the agent's
environment (managed identity / `az login` context) — no secrets in the
config.

## Permissions

Grant the agent's identity at the assessment scope:

| Role | Needed for |
| --- | --- |
| **Reader** | Resource inventory, Advisor, quotas, resource health |
| **Resource Policy Reader** | Policy compliance states |
| **Security Reader** | Defender plans, secure score, security contacts |
| **Management Group Reader** | Platform-scope hierarchy review |

Areas without permission are reported as "Not assessed" — the review never
fails outright.

## Example prompts

- "Review governance for subscription `contoso-prod` and give me an
  improvement plan."
- "Audit our landing zone under management group `mg-workloads` against CAF."
- "Platform governance review: policy coverage, RBAC sprawl, and top cost
  quick wins across all subscriptions."

## Fallback behavior

Every check has an `az` CLI / Azure Resource Graph fallback, so the skill
still works if the MCP connector is not configured — the connector adds
structured tool access (Advisor, Policy, RBAC, quotas, azqr compliance scans).

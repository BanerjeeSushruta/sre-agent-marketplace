# sre-agent-marketplace

A security-focused plugin marketplace for [Azure SRE Agent](https://azure.microsoft.com/products/sre-agent).
Register this repository as a marketplace and install the plugins as plug-and-play
operational security skills for any Azure SRE Agent.

## Register the marketplace

In your SRE Agent: **Builder > Plugins > Add marketplace**, then point to this
repository. The manifest is at [.github/plugin/marketplace.json](.github/plugin/marketplace.json).
Each plugin installs independently and is pinned to the commit at install time.

## Plugins

| Plugin | Description | Source |
| --- | --- | --- |
| [azure-architecture](plugins/azure-architecture) | Discovers Azure resources by scope (subscription/RG/tag), renders an architecture diagram via the Azure Diagram Builder MCP server, and produces SVG + PDF report with explanation. Requires one MCP connector. | [Azure Diagram Builder](https://azure-diagram-builder.yellowmushroom-f11e57c2.eastus2.azurecontainerapps.io/) |
| [mcp-owasp-top10](plugins/mcp-owasp-top10) | Azure hardening & investigation runbooks for the OWASP MCP Top 10 (securing MCP servers on Azure). Skills-only. | [microsoft/mcp-azure-security-guide](https://github.com/microsoft/mcp-azure-security-guide) |
| [openshield-cspm-remediation](plugins/openshield-cspm-remediation) | Azure CSPM remediation runbooks with ready-to-run `az` CLI fixes, mapped to CIS/NIST CSF/ISO 27001/SOC 2. Skills-only. | [openshield-org/openshield](https://github.com/openshield-org/openshield) |
| [trivy-scanner](plugins/trivy-scanner) | Standalone Trivy scanning for images, filesystems, repos, IaC, Kubernetes, and SBOMs (CVEs, misconfig, secrets, licenses). Skills-only. | [aquasecurity/trivy](https://github.com/aquasecurity/trivy) |
| [finops](plugins/finops) | Azure FinOps best-practices validator: RBAC preflight, 28-rule catalog (AZFO-001..028) incl. FOCUS/FinOps hubs adoption, reservation opportunities, log cost analysis, Azure Policy cost guardrails, PDF remediation report. | FinOps Foundation Framework / Azure Well-Architected / Microsoft FinOps toolkit |

## Structure

```
.github/
└── plugin/
    └── marketplace.json                 # marketplace manifest
plugins/
├── azure-architecture/
│   ├── plugin.json
│   ├── .mcp.json                        # azure-diagram-builder MCP server
│   ├── README.md
│   └── skills/azure_architecture/SKILL.md
├── mcp-owasp-top10/
│   ├── plugin.json
│   ├── README.md
│   └── skills/mcp_owasp_top10/SKILL.md
├── openshield-cspm-remediation/
│   ├── plugin.json
│   ├── README.md
│   └── skills/azure_cspm_remediation/SKILL.md
├── trivy-scanner/
│   ├── plugin.json
│   ├── README.md
│   └── skills/trivy_scanner/SKILL.md
└── finops/
    ├── plugin.json
    ├── README.md
    └── skills/azure_finops_validator/
        ├── SKILL.md
        ├── references/                      # rule catalog + az command reference
        ├── scripts/                         # collectors, rules engine, PDF report
        └── examples/                        # sample inventory, findings, report
```

## Notes on scope

These two upstream projects are **not** drop-in MCP servers:
`mcp-azure-security-guide` is documentation, and `openshield` is a REST/CSPM
application. Their operational value is packaged here as **skills**. To also
expose OpenShield's live scanner as an installable MCP connector, wrap its REST
API in an MCP server, host it, and add an `.mcp.json` to that plugin.

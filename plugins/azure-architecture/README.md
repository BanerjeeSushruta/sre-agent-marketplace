# Azure Architecture Plugin

Discovers existing Azure resources in a user-provided scope — **subscription**,
**resource group**, or **tag** — renders a professional Azure architecture
diagram, and delivers a **diagram file (SVG + interactive HTML)** and a **PDF
report** containing the diagram and a full explanation of every component,
connection, and resource group.

## What it installs

| Component | Name | Purpose |
| --- | --- | --- |
| Skill | `azure_architecture` | Discovery → mapping → diagram → PDF report runbook |
| MCP server | `azure-diagram-builder` | Renders Azure-branded diagrams and provides WAF validation & cost estimates |

## MCP connector setup

Installing the plugin records the MCP server requirement; configure the
connector once in the Azure portal:

1. Navigate to your SRE Agent resource
2. Select **Builder > Connectors > Add connector**
3. Configure:

| Setting | Value |
| --- | --- |
| Name | `azure-diagram-builder` |
| Connection type | Streamable-HTTP |
| URL | `https://azure-diagram-builder.yellowmushroom-f11e57c2.eastus2.azurecontainerapps.io/mcp` |
| Auth headers | None required |

Once the connector shows **Connected**, the diagram tools are available to the
agent.

## MCP tools used

| Tool | Role |
| --- | --- |
| `render_diagram` | Primary — renders SVG (for the PDF) and interactive HTML diagrams |
| `list_services` | Resolves discovered resource types to catalog service labels |
| `validate_architecture` | Optional — WAF score and findings for the report |
| `estimate_costs` | Optional — monthly cost table for the report |

## Example prompts

- "Diagram everything in subscription `contoso-prod` and explain it."
- "Create an architecture report (PDF) for resource group `rg-payments-prod`."
- "Discover all resources tagged `env=prod` and generate an architecture
  diagram with a WAF review and cost estimate."

## Permissions

The agent needs **Reader** on the target scope for resource discovery
(Azure Resource Graph / `az` CLI).

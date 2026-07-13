---
name: azure_architecture
description: Discover existing Azure resources by user-provided scope (subscription, resource group, or tag) and generate an Azure architecture diagram with a full written explanation. Uses Azure Resource Graph / az CLI for discovery and the azure-diagram-builder MCP connector (render_diagram, validate_architecture, estimate_costs, list_services) to render a professional Azure-branded diagram. Deliverables are a diagram file (SVG and interactive HTML) and a PDF report containing the diagram plus an explanation of every component, connection, and resource group. Use when asked to visualize, document, map, or diagram an Azure environment, produce an architecture report, or explain what is deployed in a subscription, resource group, or tag scope.
---

# Azure Architecture — Discovery, Diagram & PDF Report

Discover what actually exists in an Azure scope, render it as a professional
architecture diagram, and deliver a diagram file plus a PDF report explaining
the architecture.

**Required MCP connector:** `azure-diagram-builder` (Streamable-HTTP,
`https://azure-diagram-builder.yellowmushroom-f11e57c2.eastus2.azurecontainerapps.io/mcp`,
no authentication headers). Tools used: `render_diagram` (primary),
`list_services`, `validate_architecture`, `estimate_costs` (optional enrichment).

## Inputs to collect from the user

1. **Scope** (exactly one):
   - **Subscription** — subscription ID or name
   - **Resource group** — resource group name (+ subscription if ambiguous)
   - **Tag** — one or more `key=value` pairs (e.g. `env=prod`), optionally limited to a subscription
2. **Optional**: diagram title, layout direction (`TB`/`LR`), theme
   (`light`/`dark`), Azure region for cost badges, whether to include WAF
   validation and cost estimates in the report.

If the scope is missing or ambiguous, ask before discovering.

## Step 1 — Discover resources in scope

Prefer **Azure Resource Graph** (single query, cross-RG, tag-aware). Fall back
to plain `az resource list` if the `resource-graph` extension is unavailable.

```bash
# Subscription scope
az graph query -q "Resources
  | project name, type, kind, resourceGroup, location, tags,
            sku = properties.sku, subscriptionId
  | sort by type asc" --subscriptions <SUB_ID> -o json

# Resource group scope
az graph query -q "Resources
  | where resourceGroup =~ '<RG_NAME>'
  | project name, type, kind, resourceGroup, location, tags" \
  --subscriptions <SUB_ID> -o json

# Tag scope
az graph query -q "Resources
  | where tags['<KEY>'] =~ '<VALUE>'
  | project name, type, kind, resourceGroup, location, tags" -o json
```

Also collect relationship hints (used to draw connections):

```bash
# Network topology: subnet/NIC/LB/AppGW/private endpoint relationships
az graph query -q "Resources
  | where type in~ ('microsoft.network/networkinterfaces',
                    'microsoft.network/privateendpoints',
                    'microsoft.network/applicationgateways',
                    'microsoft.network/loadbalancers')
  | project name, type, props = properties" --subscriptions <SUB_ID> -o json

# App Service -> outbound dependencies (connection strings / app settings refs)
az webapp list --subscription <SUB_ID> -o json --query "[].{name:name, rg:resourceGroup}"
```

Exclude noise unless the user asks otherwise: hidden resources
(`microsoft.insights/autoscalesettings` children, smart detector alert rules),
NIC/disk children that only restate a parent VM, and
`microsoft.alertsmanagement/*`.

## Step 2 — Map discovered resources to the diagram model

Build three lists for the MCP tools:

- **services** — one entry per logical resource:
  `{ "name": "<instance name>", "type": "<Azure service type>", "description": "<role>", "groupId": "<rg-or-tier id>" }`
  - `type` must be a human service label (e.g. `App Service`, `SQL Database`,
    `Key Vault`, `Virtual Machine`, `Storage Account`, `Application Gateway`,
    `Azure OpenAI`, `AKS`). If unsure of a label, call `list_services`
    (optionally with `category`) and pick the closest match or alias.
- **groups** — one per resource group (or per tier if the user prefers):
  `{ "id": "rg-app", "label": "rg-app (East US 2)" }`
- **connections** — derived edges:
  `{ "from": "...", "to": "...", "label": "HTTPS", "type": "sync" }`
  - `sync` for request/response (HTTP, SQL), `async` for queues/events,
    `optional` for fallback/conditional paths.
  - Derive from: NIC→subnet/VNet, private endpoints→target resource, App
    Service→SQL/Key Vault/Storage (app settings), AppGW/LB backend pools,
    diagnostic settings→Log Analytics, Front Door/Traffic Manager origins.
  - When no hard evidence exists, infer conservatively and mark the edge label
    with `(inferred)`.

## Step 3 — Render the diagram (MCP tool call)

Call **`render_diagram`** on the `azure-diagram-builder` connector **twice**:

1. `format: "svg"` — static diagram for the PDF and repo artifacts.
2. `format: "html"` — interactive viewer (pan/zoom/tooltips) as a bonus artifact.

```json
{
  "title": "<scope> — Azure Architecture",
  "format": "svg",
  "direction": "TB",
  "theme": "light",
  "region": "<region or 'none'>",
  "author": "Azure SRE Agent",
  "generatedBy": "azure-architecture plugin",
  "services": [ ... ],
  "connections": [ ... ],
  "groups": [ ... ]
}
```

Save outputs as `<scope-name>-architecture.svg` and
`<scope-name>-architecture.html`.

**Optional enrichment** (include in the report when requested):
- `validate_architecture` → WAF score (0–100) + findings per pillar.
- `estimate_costs` → monthly cost table (`region`, `term: "payg"` default).

## Step 4 — Write the explanation

Structure the narrative:

1. **Overview** — scope, subscription, region(s), resource count, discovery
   timestamp.
2. **Architecture summary** — what the workload appears to be, entry points,
   data flow in 3–6 sentences.
3. **Component inventory** — table: name, service type, resource group,
   location, role in the architecture, key SKU/config.
4. **Connections & data flow** — explain each edge, marking inferred ones.
5. **Resource groups / tiers** — what each group contains and why.
6. **Optional sections** — WAF findings and cost estimate tables from Step 3.
7. **Assumptions & gaps** — anything inferred, resources excluded, and hidden
   dependencies discovery cannot see (e.g. code-level calls).

## Step 5 — Produce the PDF

Create an HTML report embedding the SVG **inline** (not linked) plus the
explanation, then convert to PDF. Try converters in this order and use the
first available:

```bash
# 1. Chromium/Edge headless
chromium --headless --disable-gpu --print-to-pdf=report.pdf report.html || \
  msedge --headless --disable-gpu --print-to-pdf=report.pdf report.html

# 2. wkhtmltopdf
wkhtmltopdf --enable-local-file-access report.html report.pdf

# 3. Python weasyprint
python -c "import weasyprint, sys; weasyprint.HTML('report.html').write_pdf('report.pdf')"

# 4. pandoc (markdown route; rasterize SVG first if needed)
pandoc report.md -o report.pdf
```

If no converter exists in the sandbox, install one
(`pip install weasyprint`) or deliver `report.html` and state clearly that it
is print-ready (File → Print → Save as PDF).

## Deliverables checklist

- [ ] `<scope>-architecture.svg` — diagram file
- [ ] `<scope>-architecture.html` — interactive diagram (bonus)
- [ ] `<scope>-architecture-report.pdf` — diagram + full explanation
- [ ] Chat summary: resource count, key findings, links/paths to artifacts

## Failure handling

- **MCP connector missing/unreachable** — tell the user to set up the
  `azure-diagram-builder` connector (URL above, Streamable-HTTP, no auth);
  as a stopgap, emit a Mermaid diagram so the report is still produced.
- **Discovery permission errors** — need `Reader` on the target scope;
  report which scope failed.
- **> ~60 resources** — offer to collapse to one node per service type per
  resource group to keep the diagram readable.
- **Unknown service type** — use `list_services` aliases; if still unmatched,
  render with the closest generic type and note it in Assumptions.

# FinOps Plugin

Skills-only Azure SRE Agent plugin that validates Azure environments against
FinOps and cost-optimization best practices — no server or MCP connector
required.

## What it adds

One skill, `azure_finops_validator`, teaching the agent to assess an Azure
subscription (or an uploaded resource export) against a structured catalog of
27 FinOps rules (`AZFO-001`…`AZFO-027`) aligned to the FinOps Foundation
Framework, the Azure Well-Architected Cost Optimization pillar, Azure Advisor
cost categories, Cost Management + Billing best practices, and the Microsoft
FinOps toolkit (FinOps hubs / FOCUS). It detects
idle/orphaned resources, unattached disks, missing budgets, tagging gaps,
Reserved Instance / Savings Plan / Hybrid Benefit opportunities, missing FOCUS
exports, and estates that have outgrown portal-only cost reporting (recommending
Microsoft FinOps hubs), then generates a findings dataset and a polished PDF
remediation report with per-rule guidance. When a FinOps hub is already
deployed, the skill uses its FOCUS-normalized Data Explorer/Fabric data as the
preferred cost source and checks hub operational hygiene.

## How it runs

- **Mode A (live)** — uses the SRE Agent's authenticated `az` CLI session
  (managed identity) to collect Resource Graph inventory, Monitor metrics,
  Advisor recommendations, budgets, and cost data, then validates and reports
  in one command.
- **Mode B (file-based)** — validates an uploaded Resource Graph / Advisor /
  Cost Management export when live Azure access isn't available.

Required RBAC on the target subscription: **Reader** + **Monitoring Reader**;
**Cost Management Reader** is optional (cost figures are best-effort). The only
third-party Python dependency is `reportlab` (PDF generation), installed on
demand.

## Install

Register the parent marketplace (`marketplace.json`) in
**Builder > Plugins > Add marketplace**, then install this plugin.

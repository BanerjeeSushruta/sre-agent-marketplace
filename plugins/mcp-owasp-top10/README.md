# MCP OWASP Top 10 — Azure Security Plugin

Skills-only Azure SRE Agent plugin providing hardening and investigation runbooks
for securing Model Context Protocol (MCP) servers on Azure, aligned with the
[OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/).

Source guidance: [microsoft/mcp-azure-security-guide](https://github.com/microsoft/mcp-azure-security-guide).

## What it adds

One skill, `mcp_owasp_top10_azure`, covering all ten risks (MCP01–MCP10) with the
mapped Azure controls (Managed Identity, Key Vault, Entra ID, API Management,
AI Content Safety Prompt Shields, Defender for Cloud, Azure Policy, Log Analytics,
Sentinel), plus triage steps and a minimum safe baseline.

## Install

Register the parent marketplace (`marketplace.json`) in
**Builder > Plugins > Add marketplace**, then install this plugin. No MCP
connector is required — this plugin contains skills only.

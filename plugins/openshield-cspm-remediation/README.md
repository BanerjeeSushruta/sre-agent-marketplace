# OpenShield Azure CSPM Remediation Plugin

Skills-only Azure SRE Agent plugin providing Cloud Security Posture Management
(CSPM) remediation runbooks for Azure, with ready-to-run `az` CLI fixes across
storage, network, identity, database, compute, Key Vault, and post-quantum
cryptography. Findings map to CIS, NIST CSF, ISO 27001, and SOC 2.

Source: [openshield-org/openshield](https://github.com/openshield-org/openshield).

## What it adds

One skill, `azure_cspm_remediation`, organized by resource domain (AZ-STOR,
AZ-NET, AZ-IDN, AZ-DB, AZ-CMP, AZ-KV, AZ-PQC). Each rule includes the check,
severity, a verified `az` remediation command, and compliance mappings.

> This plugin captures the remediation **knowledge and CLI fixes** as a portable
> skill. It does not run the OpenShield scanner. To also collect live findings,
> run the OpenShield scanner separately (or wrap its REST API as an MCP server)
> and feed results to this skill for remediation.

## Install

Register the parent marketplace (`marketplace.json`) in
**Builder > Plugins > Add marketplace**, then install this plugin. No MCP
connector is required — this plugin contains skills only.

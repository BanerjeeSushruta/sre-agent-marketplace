# Trivy Scanner Plugin

Skills-only Azure SRE Agent plugin that lets the agent run [Aqua Trivy](https://github.com/aquasecurity/trivy)
as a standalone security scanner — no server or MCP connector required.

## What it adds

One skill, `trivy_scanner`, teaching the agent to install and run Trivy across
all targets (container image, filesystem, Git repo, IaC/config, Kubernetes,
SBOM, rootfs, VM) and scanners (vulnerabilities, misconfigurations, secrets,
licenses), including severity/exit-code gating, output formats (table, JSON,
SARIF, CycloneDX, SPDX), SBOM generation, compliance reports, ignore/VEX
filtering, and offline usage.

## Why standalone

Trivy is a single self-contained binary that runs in standalone mode with a
locally downloaded database. The SRE Agent invokes it directly in the terminal,
so this plugin works plug-and-play with no hosted service.

## Install

Register the parent marketplace (`marketplace.json`) in
**Builder > Plugins > Add marketplace**, then install this plugin. The agent
installs the `trivy` binary on demand per the skill's instructions.

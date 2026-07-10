---
name: trivy_scanner
description: Standalone security scanning with Aqua Trivy. Use to scan container images, filesystems, Git repositories, IaC/config files, Kubernetes clusters/manifests, SBOMs, and VM images for vulnerabilities (CVEs), misconfigurations, hard-coded secrets, and software licenses. Covers install, the trivy CLI (image, fs, repo, config, k8s, sbom, rootfs, vm), scanner selection, severity and exit-code gating, output formats (table, json, sarif, cyclonedx, spdx), SBOM generation, compliance reports, ignore/VEX filtering, and CI/offline usage. Use whenever asked to run a vulnerability scan, container/image scan, dependency/CVE scan, IaC/Terraform/Dockerfile/Kubernetes misconfiguration scan, secret scan, or to generate an SBOM.
---

# Trivy — Standalone Security Scanner

[Trivy](https://github.com/aquasecurity/trivy) (Aqua Security, Apache-2.0) is a
single self-contained binary that finds security issues across many targets. It
runs **standalone** — it downloads its vulnerability/check databases locally and
needs no server. This skill lets the agent run Trivy directly in a terminal.

General form:
```bash
trivy <target> [--scanners <s1,s2>] [flags] <subject>
```

## When to use this skill

Use when asked to:
- Scan a container image or tarball for CVEs.
- Scan a repo/filesystem for vulnerable dependencies, secrets, or IaC misconfigurations.
- Scan Terraform, Dockerfile, Kubernetes, Helm, CloudFormation, or ARM for misconfigurations.
- Scan a running Kubernetes cluster or its manifests.
- Generate an SBOM (CycloneDX/SPDX) or scan an existing SBOM.
- Gate a CI pipeline on severity (fail the build on HIGH/CRITICAL).

## Install (pick what fits the host)

```bash
# macOS / Linux (Homebrew)
brew install trivy

# Debian/Ubuntu
sudo apt-get install -y wget gnupg
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo gpg --dearmor -o /usr/share/keyrings/trivy.gpg
echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb generic main" | sudo tee /etc/apt/sources.list.d/trivy.list
sudo apt-get update && sudo apt-get install -y trivy

# Install script (any Linux/macOS) — pins to a version
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin v0.72.0

# Docker (no install)
docker run --rm aquasec/trivy image python:3.4-alpine
```

Verify: `trivy --version`. On Windows, prefer `scoop install trivy`, `choco install trivy`, or the Docker method.

## Targets (what to scan)

| Command | Scans |
| --- | --- |
| `trivy image <name\|--input tar>` | Container image (registry or tar archive) |
| `trivy fs <path>` | Local filesystem / project directory |
| `trivy repo <url\|path>` | Git repository (remote URL or local) |
| `trivy rootfs <path>` | Unpacked root filesystem |
| `trivy config <path>` | IaC / config files (misconfiguration only) |
| `trivy k8s <cluster\|manifest>` | Kubernetes cluster or manifests (experimental) |
| `trivy sbom <sbom-file>` | Existing SBOM (CycloneDX/SPDX) for vulns + licenses |
| `trivy vm <image>` | Virtual machine image (experimental) |

## Scanners (what to find)

Select with `--scanners`: `vuln` (CVEs), `misconfig` (IaC issues), `secret`
(hard-coded secrets), `license` (software licenses).

```bash
# Full project scan: vulns + secrets + misconfig
trivy fs --scanners vuln,secret,misconfig .

# Image, vulns only (default for image includes vuln + secret)
trivy image --scanners vuln python:3.4-alpine
```

Notes:
- `secret` scanning is on by default for most targets; `misconfig` is default for `config`.
- `trivy config` only runs the misconfiguration scanner.

## Core workflows

**Container image**
```bash
trivy image nginx:1.27
trivy image --input app.tar                      # scan a saved image tar
trivy image --severity HIGH,CRITICAL nginx:1.27  # filter severities
trivy image --ignore-unfixed nginx:1.27          # only vulns with a fix
```

**Filesystem / project (dependencies + secrets + IaC)**
```bash
trivy fs --scanners vuln,secret,misconfig ./myproject
```

**Git repository**
```bash
trivy repo https://github.com/org/repo
trivy repo --branch main https://github.com/org/repo
```

**IaC / misconfiguration** (Terraform, Dockerfile, Kubernetes, Helm, CloudFormation, ARM)
```bash
trivy config ./terraform
trivy config --severity HIGH,CRITICAL ./k8s-manifests
```

**Kubernetes**
```bash
trivy k8s --report summary cluster        # summary of the current-context cluster
trivy k8s --report all cluster
trivy k8s namespace/default
```

**SBOM: generate and scan**
```bash
# Generate an SBOM from an image
trivy image --format cyclonedx --output sbom.cdx.json nginx:1.27
trivy image --format spdx-json  --output sbom.spdx.json nginx:1.27

# Scan an existing SBOM for vulnerabilities + licenses
trivy sbom sbom.cdx.json
```

## Severity, output, and CI gating

Severity levels: `UNKNOWN, LOW, MEDIUM, HIGH, CRITICAL`.

```bash
# Machine-readable output
trivy image --format json   --output result.json  nginx:1.27
trivy image --format sarif   --output result.sarif nginx:1.27   # GitHub code scanning
trivy fs    --format table   .                                   # default, human-readable

# Fail CI when qualifying issues are found
trivy image --exit-code 1 --severity CRITICAL nginx:1.27
trivy fs    --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed .
```

- `--exit-code 0` (default) always succeeds; set `--exit-code 1` to fail on findings that match the severity filter.
- Combine `--severity` + `--ignore-unfixed` to focus on actionable, fixable issues.
- Use `--quiet` for clean logs and `--timeout 10m` for large targets.
- Convert a saved JSON report to another format without rescanning: `trivy convert --format sarif --output r.sarif result.json`.

## Filtering false positives / accepted risk

- **.trivyignore** — list CVE/check IDs (one per line) to suppress:
  ```
  CVE-2023-12345
  AVD-AWS-0089
  ```
- **VEX** — provide OpenVEX/CycloneDX VEX to mark vulnerabilities not_affected:
  `trivy image --vex vex.json nginx:1.27`
- Scope with `--skip-dirs`, `--skip-files`, or a `trivy.yaml` config (`trivy --config trivy.yaml ...`).

## Compliance reports

```bash
trivy k8s --compliance k8s-cis cluster           # CIS Kubernetes Benchmark
trivy image --compliance docker-cis-1.6.0 nginx  # Docker CIS
```

## Offline / air-gapped

```bash
# On a connected host: download the DBs
trivy image --download-db-only
trivy image --download-java-db-only

# On the air-gapped host: skip update, use the cached DB
trivy image --skip-db-update --skip-java-db-update --offline-scan myimage:tag
```

## Recommended agent flow

1. Confirm Trivy is installed (`trivy --version`); install if missing.
2. Pick the **target** command from the subject (image/fs/repo/config/k8s/sbom).
3. Choose **scanners** (`vuln,secret,misconfig`) and a **severity** filter.
4. Run with `--format json --output <file>` for parsing, plus a human `table` run for the summary.
5. Summarize by severity, highlight fixable issues (`--ignore-unfixed`), and cite exact CVE/check IDs.
6. For CI, add `--exit-code 1` on the chosen severity.

## References

- Repo: https://github.com/aquasecurity/trivy
- Docs: https://trivy.dev/docs/latest/
- CLI reference: https://trivy.dev/docs/latest/references/configuration/cli/trivy/

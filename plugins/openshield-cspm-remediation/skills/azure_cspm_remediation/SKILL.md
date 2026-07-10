---
name: azure_cspm_remediation
description: Azure Cloud Security Posture Management (CSPM) remediation expertise derived from OpenShield's scanner rules and Azure CLI playbooks. Use to triage and fix Azure misconfigurations across storage, network, identity, database, compute, Key Vault, and post-quantum cryptography, with ready-to-run az CLI remediation commands. Findings map to CIS Benchmarks, NIST CSF, ISO 27001, and SOC 2. Use when investigating security posture findings, hardening Azure resources, or generating remediation steps for public blob access, open NSG rules, missing SSL enforcement, disabled purge protection, absent PIM, unencrypted disks, missing diagnostic logging, or quantum-unsafe cryptography.
---

# Azure CSPM Remediation Runbooks

Operational remediation guidance for common Azure misconfigurations, derived from
[openshield-org/openshield](https://github.com/openshield-org/openshield) — an
open-source CSPM for Azure. Each rule below includes the check, severity, a
ready-to-run Azure CLI fix, and the compliance frameworks it supports (CIS, NIST
CSF, ISO 27001, SOC 2).

## When to use this skill

Use when asked to:
- Investigate or explain an Azure security posture finding by rule ID (e.g. `AZ-STOR-001`).
- Generate a safe `az` CLI remediation for a misconfiguration.
- Harden storage, network, identity, database, compute, or Key Vault resources.
- Identify classical cryptographic assets that need post-quantum migration.

## How to use a remediation

1. **Confirm the finding** and the exact resource (name + resource group + subscription).
2. **Understand impact before acting.** Fixes that delete resources or enable irreversible settings (e.g. Key Vault purge protection) require confirmation.
3. **Run the `az` command** with `az login` completed and the correct subscription set (`az account set --subscription <id>`).
4. **Re-scan / verify** with the noted verification command.

> Safety: prefer least-privilege, reversible changes. Never delete a resource (e.g. an empty load balancer) without confirming it is truly unused. Purge protection and similar settings **cannot be undone**.

---

## Storage (AZ-STOR)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-STOR-001 | Public blob access enabled | HIGH |
| AZ-STOR-002 | Secure transfer (HTTPS-only) not enforced | HIGH |
| AZ-STOR-003 | Blob soft delete / versioning not enabled | MEDIUM |
| AZ-STOR-004 | Storage diagnostic logging not enabled | MEDIUM |
| AZ-STOR-005 | Geo-redundant storage (GRS) not enabled | LOW |

**AZ-STOR-001 — Disable public blob access**
```bash
az storage account update \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --allow-blob-public-access false
```

**AZ-STOR-002 — Enforce HTTPS-only traffic**
```bash
az storage account update \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --https-only true
```

Frameworks: CIS 3.x, NIST CSF PR.DS, ISO 27001 A.8, SOC 2 CC6.

---

## Network (AZ-NET)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-NET-001..010 | NSG/open-port, public IP, and exposure checks | HIGH–MEDIUM |
| AZ-NET-008 | Load balancer with no backend pool configured | LOW |
| AZ-NET-011 | Network Watcher not enabled in all regions | LOW |
| AZ-NET-012 | NSG flow logs not enabled | MEDIUM |
| AZ-NET-013 | Azure Firewall not deployed for VNet | MEDIUM |
| AZ-NET-014 | VNet peering gateway transit misconfiguration | LOW |
| AZ-NET-015 | Public DNS zone enumeration exposure | LOW |

**AZ-NET-008 — Remove empty load balancer (or add a backend pool)**
```bash
# Option 1: delete if no longer needed (confirm first)
az network lb delete --resource-group "$RESOURCE_GROUP" --name "$LB_NAME"

# Option 2: add a backend pool if still required
az network lb address-pool create \
  --resource-group "$RESOURCE_GROUP" \
  --lb-name "$LB_NAME" \
  --name "$POOL_NAME"
```

**AZ-NET-012 — Enable NSG flow logs** (send to a Log Analytics workspace via Network Watcher; enables traffic analytics for exfiltration detection).

Frameworks: CIS 6.x, NIST CSF PR.AC/DE.CM, ISO 27001 A.13, SOC 2 CC6.

---

## Identity (AZ-IDN)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-IDN-001..002 | MFA / conditional access gaps | HIGH |
| AZ-IDN-003 | Entra ID risky/legacy configuration | MEDIUM |
| AZ-IDN-004 | Privileged Identity Management (PIM) not configured for admin roles | HIGH |
| AZ-IDN-005..009 | Additional Entra ID identity posture checks | MEDIUM |

**AZ-IDN-004 — Configure PIM for admin roles** (requires Entra ID Premium P2; largely portal-driven):
- Portal → Entra ID → Identity Governance → Privileged Identity Management.
- For each admin role (Global Administrator, Privileged Role Administrator, Security Administrator, User Administrator, Application Administrator, etc.) set: activation max duration ≤ 8h, require MFA on activation, require justification, require approval (for Global Admin).
- Convert permanent assignments to **eligible**.
- Verify eligibility schedules via CLI:
```bash
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/roleManagement/directory/roleEligibilitySchedules" \
  --query "value[].{role:roleDefinitionId, principal:principalId, status:status}" \
  --output table
```

Frameworks: CIS 1.x, NIST CSF PR.AC, ISO 27001 A.9, SOC 2 CC6.1.

---

## Database (AZ-DB)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-DB-001..002 | Public network access / TDE checks | HIGH |
| AZ-DB-003 | PostgreSQL Flexible Server SSL enforcement disabled | HIGH |
| AZ-DB-004 | SQL Server firewall allows all Azure services | HIGH |

**AZ-DB-003 — Enforce SSL on PostgreSQL Flexible Server**
```bash
az postgres flexible-server parameter set \
  --resource-group "$RESOURCE_GROUP" \
  --server-name "$SERVER_NAME" \
  --name require_secure_transport \
  --value ON
# Verify:
az postgres flexible-server parameter show \
  --name require_secure_transport --server-name "$SERVER_NAME" --resource-group "$RESOURCE_GROUP"
```

Frameworks: CIS 4.x, NIST CSF PR.DS, ISO 27001 A.10/A.13, SOC 2 CC6.7.

---

## Compute (AZ-CMP)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-CMP-001 | VM exposure / baseline misconfiguration | MEDIUM |
| AZ-CMP-002 | VM disk not protected by CMK or Azure Disk Encryption | HIGH |
| AZ-CMP-003 | VM without endpoint protection installed | MEDIUM |
| AZ-CMP-004 | VM without automatic OS patching enabled | MEDIUM |

**AZ-CMP-004 — Enable automatic OS patch assessment/patching**
```bash
az vm update \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --set osProfile.linuxConfiguration.patchSettings.patchMode=AutomaticByPlatform
```

Frameworks: CIS 7.x, NIST CSF PR.IP, ISO 27001 A.12, SOC 2 CC7.1.

---

## Key Vault (AZ-KV)

| Rule | Check | Severity |
| --- | --- | --- |
| AZ-KV-001 | Key Vault baseline misconfiguration | MEDIUM |
| AZ-KV-002 | Key Vault public network access enabled | HIGH |
| AZ-KV-003 | Key Vault without diagnostic logging | MEDIUM |
| AZ-KV-004 | Key Vault purge protection disabled | HIGH |
| AZ-KV-005 | Certificate expiring within 30 days | MEDIUM |

**AZ-KV-002 — Disable public network access**
```bash
az keyvault update \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VAULT_NAME" \
  --public-network-access Disabled
```

**AZ-KV-004 — Enable purge protection** (irreversible — confirm first)
```bash
az keyvault update \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VAULT_NAME" \
  --enable-purge-protection true
```

Frameworks: CIS 8.x, NIST CSF PR.DS, ISO 27001 A.10, SOC 2 CC6.

---

## Post-Quantum Cryptography (AZ-PQC)

Adversaries harvest encrypted traffic today to decrypt later once quantum
computers are available ("Harvest Now, Decrypt Later"). These rules identify
classical cryptographic assets needing migration.

| Rule | Check |
| --- | --- |
| AZ-PQC-001 | TLS using RSA/ECDH key exchange on App Services |
| AZ-PQC-002 | Key Vault keys using RSA/ECC vulnerable to Shor's algorithm |
| AZ-PQC-003 | Certificates using classical signature algorithms |

**Remediation direction.** Inventory affected assets and plan migration toward
NIST post-quantum standards: **FIPS 203 (ML-KEM)** for key establishment,
**FIPS 204 (ML-DSA)** and **FIPS 205 (SLH-DSA)** for signatures. Prioritize
long-lived secrets and externally reachable TLS endpoints.

Frameworks: NIST FIPS 203/204/205, NIST CSF PR.DS.

---

## Compliance mapping

OpenShield maps every finding to framework JSON for **CIS Benchmarks**, **NIST
CSF**, **ISO 27001**, and **SOC 2**. When reporting a finding, cite the rule ID,
severity, affected resource, the remediation command, and the mapped control so
the fix is audit-traceable.

## References

- Repo: https://github.com/openshield-org/openshield
- Scanner rules: `scanner/rules/` · Remediation playbooks: `playbooks/cli/`
- Compliance frameworks: `compliance/frameworks/`

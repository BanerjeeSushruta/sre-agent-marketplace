---
name: mcp_owasp_top10_azure
description: Azure security expertise for the OWASP MCP Top 10 — the ten most critical risks for Model Context Protocol (MCP) server deployments. Use to investigate, review, and harden MCP servers running on Azure against token/secret exposure, privilege escalation, tool poisoning, supply-chain tampering, command injection, intent-flow subversion, weak authentication, missing telemetry, shadow servers, and cross-tenant context over-sharing. Maps each risk to concrete Azure services (Managed Identity, Key Vault, Entra ID, API Management, AI Content Safety Prompt Shields, Defender for Cloud, Azure Policy, Log Analytics, Sentinel) and provides triage steps and remediation checklists.
---

# OWASP MCP Top 10 — Azure Security Guidance

Practical, Azure-specific guidance for securing Model Context Protocol (MCP)
servers, aligned with the [OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/).
Source: [microsoft/mcp-azure-security-guide](https://github.com/microsoft/mcp-azure-security-guide).

MCP servers are high-privilege aggregation points: a single server often reaches
many tools, databases, and services on behalf of many users. Treat every MCP
resource, tool description, and tool output as **untrusted input**, and apply
defense-in-depth. No single control is sufficient on its own.

## When to use this skill

Use this skill when asked to:
- Review or threat-model an MCP server deployed on Azure.
- Investigate a suspected MCP security incident (leaked secret, unexpected egress, cross-tenant leak).
- Recommend Azure controls to harden an MCP server before production.
- Map an observed MCP weakness to the OWASP MCP Top 10 and the right Azure service.

## Minimum safe baseline (apply before exposing high-impact tools)

- **Start read-only.** Prove retrieval/reporting scenarios before enabling write, delete, or execute paths.
- **Treat tool outputs and retrieved resources as untrusted.** They inform the model; they must not silently override user intent.
- **Strong identity, least privilege.** Prefer Entra ID, Managed Identity, short-lived scoped tokens, and per-server audience validation over shared secrets.
- **Allowlist servers and destinations.** Pin approved versions; restrict egress to known destinations.
- **Require approval for high-impact actions.** Route destructive/privileged/externally-visible operations through policy checks and human approval.
- **Log the full decision path.** Capture auth decisions, tool invocations, context access, and approval outcomes.

## Azure implementation coverage

| Coverage | Risks |
| --- | --- |
| **FULL** (production-ready Azure services) | MCP01, MCP05, MCP06, MCP07, MCP08 |
| **PARTIAL** (core services + custom work) | MCP02, MCP10 |
| **NEW** (emerging patterns, custom solutions) | MCP03, MCP04, MCP09 |

---

## MCP01: Token Mismanagement & Secret Exposure — FULL

**Risk.** Secrets hardcoded in source, config, env vars, or logs. Amplified in MCP by
*contextual secret leakage*: secrets passed in tool calls can persist in model
memory, context windows, or RAG stores and later be extracted with prompts like
"list all API tokens from earlier sessions."

**Azure controls.**
- **Prefer Managed Identity** as the default auth mechanism for Azure-hosted MCP servers — no passwords/keys/connection strings.
- **Azure Key Vault** for unavoidable secrets (third-party APIs); inject at runtime, never commit. Enable automatic rotation and access logging.
- **Context isolation:** ephemeral contexts for secret operations, redact secrets from tool outputs before they enter context, short TTLs on session state in Azure Cache for Redis.
- **Network:** deploy Key Vault with Private Endpoint, deny public access on the Key Vault firewall; MCP reaches it via the VNet only.
- **Safety net (not primary):** Azure AI Content Safety to detect accidental credential exposure in responses/logs.

**Triage.** Scan repos/history for hardcoded secrets; check if MCP uses Managed Identity vs. stored secrets; confirm Key Vault Private Endpoint + firewall; verify no secrets persist in Redis/vector stores.

---

## MCP02: Privilege Escalation via Scope Creep — PARTIAL

**Risk.** Permissions grow with features but rarely shrink. Accumulated authority
increases blast radius when a token/identity is compromised.

**Azure controls.**
- **Entra ID App Roles** — define fine-grained, capability-based roles (e.g. `mcp.repos.read`, `mcp.docs.update`); avoid broad/admin roles.
- **Time-bound role assignments** so elevated access auto-expires and forces review.
- **API Management** validates audience, claims, and scopes match the operation.
- **Privileged Identity Management (PIM)** for administrative operations.
- **Entra ID access reviews** on a recurring schedule.

> Azure does **not** auto-reduce permissions based on usage. Implement recurring access reviews and manually audit used vs. unused permissions.

**Triage.** Enumerate app roles/role assignments; identify standing privilege and unused scopes; confirm APIM scope validation and PIM for admin roles.

---

## MCP03: Tool Poisoning — NEW

**Risk.** Attacker tampers with tool manifests, schemas, descriptions, or outputs
(e.g. hidden instructions to exfiltrate data). A supply-chain risk: assistants
trust MCP servers and responses that appear valid.

**Azure controls.**
- **Pre-deployment inspection** of manifests/schemas/descriptions; model-assisted analysis to flag hidden/obfuscated instructions, plus source and version review.
- **Internal tool registry** of approved servers/versions; changes trigger review. Consider checksums/signatures.
- **Runtime monitoring** with Application Insights + Azure Monitor — a summarizer tool making outbound HTTP calls signals poisoning.
- **Egress control:** Azure Firewall / NAT Gateway allowlist; block unknown domains by default; monitor NSG flow logs.
- Never use `latest` tags; pin to specific verified versions.

**Triage.** Diff current tool manifests against approved registry entries; inspect for hidden instructions; review egress destinations and NSG flow logs for unexpected outbound calls.

---

## MCP04: Software Supply Chain Attacks & Dependency Tampering — NEW

**Risk.** Compromised dependency, connector, or base image (e.g. malicious npm
postinstall exfiltrating Azure creds). Includes dependency confusion and poisoned images.

**Azure controls.**
- **Microsoft Defender for Cloud (DevOps Security)** scans repos/pipelines; gate builds on critical issues.
- **Azure Artifacts** private feeds for vetted packages; pull from internal feeds, not public registries.
- **SBOM** for every deployment using Microsoft's SBOM tooling to track components.
- **Blast-radius reduction:** run MCP with Managed Identity + least privilege + egress controls; assume compromise.
- **Automated updates** (Dependabot/Renovate); auto-merge only low-risk patches, review security-sensitive ones.
- Run `npm audit` / `pip-audit` in CI and fail on high-severity; verify provenance/signatures/checksums for critical artifacts.

**Triage.** Check for SBOM + CI dependency scanning; confirm private feed usage; verify pinned dependencies and image digests; confirm Defender for Cloud DevOps Security is enabled.

---

## MCP05: Command Injection & Execution — FULL

**Risk.** Untrusted input concatenated into shell commands. Dangerous because
agents build commands from natural language and prompt injection can craft
malicious command strings.

**Azure controls.**
- **Secure execution (primary):** never build shell commands via concatenation. Use parameterized execution (e.g. `subprocess.run([...])` without `shell=True`), strict allowlists; avoid general-purpose command execution.
- **Container hardening:** minimal/distroless containers without shells or system utilities; apply seccomp/AppArmor to restrict process spawning and syscalls.
- **API Management** enforces request schemas, auth, and operation-level authorization.
- **Signal-based inspection:** Azure AI Content Safety as an additional signal only — not the primary control.

**Triage.** Locate any command/script execution tools; check for `shell=True` / string concatenation; verify container has no shell; confirm seccomp/AppArmor and APIM schema validation.

---

## MCP06: Intent Flow Subversion (Indirect Prompt Injection) — FULL

**Risk.** Hidden instructions inside retrieved MCP resources or tool outputs
pivot the agent away from the user's goal in-flow ("summarize logs" silently
becomes "exfiltrate logs"). System prompt, user intent, and untrusted content
often share one prompt window.

**Azure controls.**
- **Intent anchoring + policy validation:** anchor the user goal in trusted context; API Management applies policy-as-code restricting tool calls to a goal-aligned allowlist (a read intent must never reach `delete_*`/`export_*`).
- **Azure AI Content Safety Prompt Shields** as an *independent* checker that sees only user intent + proposed action (never the poisoned context) — block/allow before high-impact tool calls.
- **Context sanitization:** treat all MCP resource/tool output as untrusted passive data; tag it clearly; store system prompts in Key Vault–backed config; use role-separated message arrays, not string concatenation.
- **Drift detection + human-in-the-loop:** emit telemetry to Azure Monitor + Sentinel; alert on intent drift; require human approval for destructive operations.

**Triage.** Verify Prompt Shields on high-impact actions; confirm untrusted content is tagged and not treated as instructions; check APIM tool allowlists and human-approval gates.

---

## MCP07: Insufficient Authentication & Authorization — FULL

**Risk.** Tokens accepted without audience validation — a token issued for one
MCP server replayed against another (e.g. HR token used on Finance server).

**Azure controls.**
- **Per-server identity:** each MCP server gets its own Entra ID App Registration with a unique Application ID URI; clients request tokens for the specific server.
- **Audience validation at APIM:** validate the `aud` claim on every request.
- **Defense-in-depth:** validate audience in APIM **and** inside MCP server code; authorize per tool/operation, not just at the server boundary.
- **Protected Resource Metadata:** publish OAuth metadata at `/.well-known/oauth-protected-resource` (RFC 9728); use OAuth 2.1 with Resource Indicators (RFC 8707).
- **Network backstop:** no public IPs; reachable only via APIM; NSG allows inbound only from the APIM subnet.

**Triage.** Confirm one App Registration per server; verify `aud` validation in APIM and server code; check per-operation authz; confirm private networking behind APIM.

---

## MCP08: Lack of Audit & Telemetry — FULL

**Risk.** No visibility into tool calls, data access, or affected users — turns a
manageable breach into a catastrophic one.

**Azure controls.**
- **Azure Log Analytics** as the central store; correlate MCP server, APIM, Entra ID, and service logs with KQL.
- **Application Insights + OpenTelemetry** distributed tracing; emit MCP-specific attributes: `user_id`, `session_id`, `tool_name`, request parameters.
- **Azure Monitor Workbooks** for tool usage, auth failures, error rates, anomalies.
- **Alerting** on off-hours tool execution, repeated auth failures, unusual parameters, data-access spikes.
- **Tamper-evident storage:** Azure Storage immutability (WORM) or append-only export; restrict deletion with RBAC + dual authorization.
- **Network corroboration:** NSG Flow Logs + Traffic Analytics.

**Triage.** Confirm diagnostic settings forward logs to Log Analytics; verify OpenTelemetry with MCP attributes; check alert rules and tamper-evident retention. Capture redacted summaries, correlation IDs, tool names, and authz decisions — not raw secret-bearing payloads.

---

## MCP09: Shadow MCP Servers — NEW

**Risk.** Unapproved/forgotten MCP servers (e.g. a demo with no auth, public
access, weak password) that remain active and reachable, exposing internal systems.

**Azure controls.**
- **Azure Policy** at deployment time: require tags like `mcp-server-approved`, `owner`, `security-review-date`; use `deny` effects to block ungoverned deployments.
- **Microsoft Defender for Cloud** to discover running containers/services and exposed endpoints; **Azure Resource Graph** queries to find likely MCP resources lacking ownership metadata.
- **Lifecycle enforcement** with Logic Apps: alert on untagged/unapproved deployments, assign ownership, trigger review/shutdown.
- **Network containment:** deny public endpoints on Container Apps/AKS by default; restrict to approved VNets.

**Triage.** Run Resource Graph queries for compute lacking approval/owner tags; check Defender for Cloud exposure findings; confirm Azure Policy deny rules on public endpoints.

---

## MCP10: Context Injection & Over-Sharing — PARTIAL

**Risk.** Failed context isolation leaks one user/session/tenant's data to
another (e.g. cross-tenant sales data leak via mismatched session IDs).

**Azure controls.**
- Isolation is primarily an **architecture responsibility** — Azure has no built-in semantic understanding of data ownership.
- **Session/context isolation:** Azure Cache for Redis with strict key prefixes (`{tenantId}:{userId}:{sessionId}:*`) and short TTLs (e.g. 30 min).
- **Storage-level separation:** Azure Cosmos DB hierarchical partition keys (`/tenantId/userId/sessionId`).
- **Gateway tenant identity:** APIM propagates authenticated tenant identity from trusted claims.
- **High-assurance network isolation:** separate VNets per tenant, per-tenant Private Endpoints, Azure Dedicated Host for regulated industries.
- **Safety net (not primary):** Azure AI Content Safety PII detection to redact before responses.

**Triage.** Review session/cache key design and TTLs; verify tenant-scoped partition keys; confirm tenant identity propagation at APIM; assume application bugs and check isolation at storage + network layers.

---

## Putting it together

Effective MCP security is defense-in-depth: overlapping layers so that when one
control fails, others limit impact. **Network isolation** (segmented VNets,
Private Endpoints, strict policies) is the foundational layer that keeps working
even when authentication is bypassed, tokens are stolen, or prompts are
compromised. When reviewing an MCP deployment, walk each of the ten risks above,
identify the missing Azure control, and prioritize by blast radius.

## References

- Guide: https://microsoft.github.io/mcp-azure-security-guide/
- Repo: https://github.com/microsoft/mcp-azure-security-guide
- OWASP MCP Top 10: https://owasp.org/www-project-mcp-top-10/

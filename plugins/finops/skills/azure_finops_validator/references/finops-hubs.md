# FinOps hubs — detection, usage, and recommendation guidance

Reference for rules **AZFO-026** (FOCUS export) and **AZFO-027** (FinOps data
platform), and for using an existing hub as a data source. Based on the
[FinOps hubs overview](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/hubs/finops-hubs-overview)
from the Microsoft FinOps toolkit.

## What a FinOps hub is

FinOps hubs extend Cost Management into a scalable, FOCUS-aligned data platform
for cost analytics. A hub instance deploys, into one resource group:

- **Data Lake Storage Gen2** account — staging (`msexports` container) and
  ingestion (`ingestion` container) of exported cost data, converted to parquet
- **Data Factory** — ingestion + cleanup pipelines
- **Key Vault** — Data Factory managed-identity credentials
- Optional: **Azure Data Explorer (Kusto)** cluster or **Microsoft Fabric
  Real-Time Intelligence** — analytical datastore (`Hub` and `Ingestion`
  databases) for KQL queries, dashboards, and the Power BI KQL reports

Estimated cost: from ~$120/mo (single-node ADX) or ~$300/mo (F2 Fabric) plus
~$10/mo per $1M monitored; ~$5 per $1M storage-only. ~20 GB data per $1M spend.

## Detecting an existing hub (Mode A)

Look for the co-deployed resource set. Typical checks:

```bash
# Resource groups or Data Factories named after the default template
az graph query -q "Resources | where name contains 'finops-hub' or resourceGroup contains 'finops' | project name, type, resourceGroup, subscriptionId" --first 100

# Hub instances tag their resources; also check for the telltale trio in one RG
az graph query -q "Resources | where type in~ ('microsoft.datafactory/factories','microsoft.kusto/clusters','microsoft.keyvault/vaults','microsoft.storage/storageaccounts') | summarize types=make_set(type) by resourceGroup, subscriptionId | where array_length(types) >= 3" --first 100

# FOCUS exports configured on the subscription (AZFO-026)
az costmanagement export list --scope "/subscriptions/<sub-id>" --query "[].{name:name, dataset:properties.definition.type, recurrence:properties.schedule.recurrence}"
```

Interpretation:
- **FOCUS export exists** → AZFO-026 passes for that scope.
- **Hub resource set found** → AZFO-027 passes; prefer the hub as a data
  source (below) and do not flag the hub's own storage/ADX/Data Factory
  resources as idle/orphaned without checking the hub's ingestion schedule —
  low steady-state utilization is normal between export runs.
- **Neither, and the engagement spans multiple subscriptions/tenants** →
  raise AZFO-027 with the deployment guidance below.

## Using an existing hub as a data source

If a hub with Data Explorer/Fabric RTI is present and the agent's identity has
**Viewer on the `Hub` and `Ingestion` databases**, prefer querying it for cost
figures instead of (or in addition to) the best-effort Cost Management query in
`collect_azure_data.py` — it is faster, FOCUS-normalized, and spans all
configured scopes:

```bash
az kusto query --cluster-name <cluster> --database-name Hub \
  --query "Costs | where ChargePeriodStart >= startofmonth(now(-30d)) | summarize EffectiveCost=sum(EffectiveCost) by SubAccountName, ServiceName | top 20 by EffectiveCost"
```

Useful FOCUS columns (see the toolkit
[data dictionary](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/help/data-dictionary)):
`EffectiveCost`, `BilledCost`, `ListCost`, `ContractedCost` (the deltas give
negotiated vs commitment-discount savings), `ChargePeriodStart`,
`ServiceName`, `ResourceId`, `SubAccountId`, `CommitmentDiscountStatus`.
Populate `monthly_cost_usd` in the resource inventory from `EffectiveCost`
aggregated by `ResourceId` for more accurate severity ranking in the report.

## Recommending a hub (AZFO-027 remediation detail)

Prerequisites and steps, in order:

1. Register the **Microsoft.CostManagementExports** and **Microsoft.EventGrid**
   resource providers on the subscription.
2. Plan **public or private networking** with network admins before deploying
   (private endpoints are supported but must be decided up front).
3. Optional: set up Microsoft Fabric Real-Time Intelligence instead of ADX.
4. Deploy the template: `aka.ms/finops/hubs/deploy` (Azure),
   `/gov` (Azure Government), `/china` (21Vianet, MCA only).
5. Create FOCUS exports in Cost Management for each scope, or grant FinOps
   hubs access to manage exports. CSP/MCA note: management-group exports are
   not supported — configure per subscription.
6. Connect the Data Explorer dashboards or the toolkit Power BI reports
   (`PowerBI-kql.zip` for ADX, `PowerBI-storage.zip` for storage-only).

Required permissions to relay to the user:

| Action | Role |
| --- | --- |
| Deploy the hub template | Contributor + RBAC Administrator, or Owner |
| Configure exports (sub/RG scope) | Cost Management Contributor |
| Configure exports (EA billing) | Enterprise Reader / Department Reader / Account Owner |
| Configure exports (MCA billing) | Contributor on billing account/profile/invoice section |
| Power BI storage reports | Storage Blob Data Reader (or SAS) |
| Power BI/agent KQL access | Viewer on `Hub` and `Ingestion` databases |

MOSA (pay-as-you-go) subscriptions can't produce FOCUS exports — hubs 0.2+
don't support them; note this instead of recommending a hub.

## Hub hygiene (if the user already runs one)

Operational best practices from the toolkit team, worth checking during an
assessment of a subscription that hosts a hub:

- **Don't modify built-in pipelines or data in the `msexports` container**;
  apply custom logic via new Data Factory pipelines monitoring the `ingestion`
  container, with a distinct prefix to avoid clashing with future releases.
- **Don't hand-edit `hub.bicep`/`finops-hub/main.bicep`**; wrap the hub in
  your own Bicep module that references the released template so upgrades
  stay clean — track any unavoidable local changes and reapply on upgrade.
- Keep the hub current with toolkit releases (dataset versions are
  backwards-compatible; new columns may be added).
- Custom alerting belongs downstream (Power Automate, Data Factory,
  Functions) reading from Data Lake/ADX — not inside the hub pipelines.

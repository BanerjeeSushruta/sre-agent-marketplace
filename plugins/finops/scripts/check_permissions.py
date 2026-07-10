#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - Preflight Permissions Check
---------------------------------------------------------------------
Run FIRST, before any collection. Verifies the signed-in identity and
reports which RBAC roles required by this skill are held, missing, or
undeterminable on the target subscription, and what parts of the
validation each gap will skip. Never fails the pipeline on missing
optional roles — it informs, so the agent can relay the table to the
user before spending time on a full run.

Exit codes:
    0  authenticated; report printed (missing roles are warnings only)
    1  Azure CLI not authenticated / subscription not reachable
    2  Reader role definitely missing (nothing useful can run)

Usage:
    python3 check_permissions.py --subscription-id <sub-id> [--json]
"""

import argparse
import json
import subprocess
import sys

# role name -> (required?, what it gates)
REQUIRED_ROLES = {
    "Reader": (True, "Resource Graph inventory, Advisor recommendations, "
                     "reservation recommendations — the whole assessment"),
    "Monitoring Reader": (True, "Azure Monitor metrics (idle/right-sizing rules "
                                "AZFO-001/002/008/021/023/025 and Log Analytics "
                                "ingestion volumes)"),
    "Cost Management Reader": (False, "Cost figures per resource, budgets check "
                                      "(AZFO-017) and savings ranking accuracy"),
    "Log Analytics Reader": (False, "Per-table ingestion breakdown for deeper "
                                    "log cost analysis (AZFO-021/022/028 detail)"),
}

# Roles that fully include a required role's permissions (superset match).
ROLE_SUPERSETS = {
    "Reader": ["Reader", "Contributor", "Owner", "Monitoring Contributor"],
    "Monitoring Reader": ["Monitoring Reader", "Monitoring Contributor", "Contributor", "Owner"],
    "Cost Management Reader": ["Cost Management Reader", "Cost Management Contributor", "Contributor", "Owner"],
    "Log Analytics Reader": ["Log Analytics Reader", "Log Analytics Contributor", "Contributor", "Owner", "Reader"],
}


def run_az(args, timeout=90):
    result = subprocess.run(["az"] + args + ["-o", "json"], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500])
    return json.loads(result.stdout) if result.stdout.strip() else None


def get_account(subscription_id):
    try:
        account = run_az(["account", "show"])
    except Exception as e:
        print("ERROR: Azure CLI is not authenticated. For Azure SRE Agent this "
              "should be the agent's managed identity; otherwise run `az login` "
              f"or configure a service principal.\nDetail: {e}", file=sys.stderr)
        sys.exit(1)
    if subscription_id and account.get("id") != subscription_id:
        try:
            run_az(["account", "set", "--subscription", subscription_id])
            account = run_az(["account", "show"])
        except Exception as e:
            print(f"ERROR: cannot access subscription {subscription_id} with this "
                  f"identity: {e}", file=sys.stderr)
            sys.exit(1)
    return account


def get_role_assignments(subscription_id, account):
    """Best-effort: list role assignments for the current principal at or above
    the subscription scope. Returns a list of role definition names, or None if
    they could not be determined (e.g., no permission to read assignments)."""
    user = account.get("user", {})
    assignee = user.get("name")  # UPN for users, appId for SPs/MIs
    scope = f"/subscriptions/{subscription_id}"
    attempts = [
        ["role", "assignment", "list", "--assignee", assignee, "--scope", scope,
         "--include-inherited", "--include-groups"],
        ["role", "assignment", "list", "--assignee", assignee, "--scope", scope,
         "--include-inherited"],
        ["role", "assignment", "list", "--scope", scope, "--include-inherited"],
    ]
    for args in attempts:
        try:
            assignments = run_az(args) or []
            names = sorted({a.get("roleDefinitionName") for a in assignments if a.get("roleDefinitionName")})
            if names or args is attempts[-1]:
                return names
        except Exception:
            continue
    return None


def probe_fallback(subscription_id):
    """If role assignments can't be read, probe with harmless read calls."""
    status = {}
    try:
        run_az(["graph", "query", "-q", "Resources | limit 1", "--subscriptions", subscription_id])
        status["Reader"] = "HELD (probe)"
    except Exception:
        status["Reader"] = "MISSING (probe failed)"
    try:
        run_az(["consumption", "budget", "list", "--subscription", subscription_id], timeout=60)
        status["Cost Management Reader"] = "HELD (probe)"
    except Exception:
        status["Cost Management Reader"] = "UNKNOWN (probe failed)"
    return status


def evaluate(role_names):
    status = {}
    for role, (required, _) in REQUIRED_ROLES.items():
        if role_names is None:
            status[role] = "UNKNOWN"
        elif any(held in ROLE_SUPERSETS[role] for held in role_names):
            status[role] = "HELD"
        else:
            status[role] = "MISSING"
    return status


def main():
    parser = argparse.ArgumentParser(description="Preflight RBAC check for the FinOps validation pipeline.")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--json", action="store_true", help="Also print machine-readable JSON result")
    parser.add_argument("--json-output", default=None,
                        help="Write the machine-readable result to this file (consumed by "
                             "generate_report.py for the Identity & Access Coverage section)")
    args = parser.parse_args()

    account = get_account(args.subscription_id)
    principal = account.get("user", {})
    print(f"Identity: {principal.get('name', 'unknown')} ({principal.get('type', 'unknown')})")
    print(f"Subscription: {account.get('name')} ({account.get('id')})\n")

    role_names = get_role_assignments(args.subscription_id, account)
    status = evaluate(role_names)

    if all(v == "UNKNOWN" for v in status.values()):
        print("Could not read role assignments (identity may lack "
              "Microsoft.Authorization/roleAssignments/read). Falling back to "
              "read-probes...\n")
        status.update(probe_fallback(args.subscription_id))

    width = max(len(r) for r in REQUIRED_ROLES)
    print(f"{'Role'.ljust(width)}  {'Need':<9} {'Status':<24} Gates")
    print("-" * 110)
    reader_missing = False
    for role, (required, gates) in REQUIRED_ROLES.items():
        need = "required" if required else "optional"
        st = status.get(role, "UNKNOWN")
        print(f"{role.ljust(width)}  {need:<9} {st:<24} {gates}")
        if role == "Reader" and st.startswith("MISSING"):
            reader_missing = True

    print()
    if role_names:
        print(f"Roles held at subscription scope: {', '.join(role_names)}")
    missing = [r for r, s in status.items() if str(s).startswith("MISSING")]
    if reader_missing:
        print("\nReader is missing — the assessment cannot run. Ask the subscription "
              "owner to grant Reader to this identity:\n"
              f"  az role assignment create --assignee <principal-id> --role Reader "
              f"--scope /subscriptions/{args.subscription_id}")
    elif missing:
        print(f"\nMissing role(s): {', '.join(missing)}. The pipeline will still run; "
              "the gated checks above will be skipped and noted in the report. "
              "Grant commands:")
        for role in missing:
            print(f"  az role assignment create --assignee <principal-id> --role "
                  f"\"{role}\" --scope /subscriptions/{args.subscription_id}")
    else:
        print("\nAll required roles are held (or probed OK). Proceeding is safe.")

    if args.json or args.json_output:
        payload = {
            "identity": principal,
            "subscription_id": account.get("id"),
            "subscription_name": account.get("name"),
            "roles_held": role_names,
            "roles": [
                {"role": role, "need": "required" if required else "optional",
                 "status": status.get(role, "UNKNOWN"), "gates": gates}
                for role, (required, gates) in REQUIRED_ROLES.items()
            ],
        }
        if args.json_output:
            with open(args.json_output, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"\nPreflight result written to {args.json_output}")
        if args.json:
            print("\n" + json.dumps(payload, indent=2))

    sys.exit(2 if reader_missing else 0)


if __name__ == "__main__":
    main()

import json
import os
import sys

import boto3
import requests
from botocore.exceptions import ClientError

ENDPOINT = "https://api.newrelic.com/graphql"
TIMEZONE = "America/Chicago"

# ─── S3 State Backend ────────────────────────────────────────────────────────
S3_BUCKET = "newrelic-downtime"
S3_REGION = "us-east-1"

# ─── Condition IDs live here, not in Jenkins ────────────────────────────────
ENVIRONMENT_CONFIG = {
    "App": {
        "key": "app",
        "condition_ids": ["44735169", "44735098", "55638202"],
        "label": "TCP Production App Service Downtime Muting Rule",
    },
    "Admin": {
        "key": "admin",
        "condition_ids": ["44760251", "44735098", "55638202"],
        "label": "TCP Production Admin Service Downtime Muting Rule",
    },
    "Sandbox": {
        "key": "sandbox",
        "condition_ids": ["52535955", "52535889", "4081891"],
        "label": "TCP Sandbox Service Downtime Muting Rule",
    },
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_stack_suffix(stack_names):
    return "-".join(
        s.strip().replace(" ", "-").replace("_", "-")
        for s in stack_names
        if s.strip()
    )


def execute_graphql(api_key, query):
    headers = {
        "Content-Type": "application/json",
        "API-Key": api_key,
    }
    response = requests.post(
        ENDPOINT,
        headers=headers,
        json={"query": query},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _s3_client():
    return boto3.client("s3", region_name=S3_REGION)


# ─── S3 State ─────────────────────────────────────────────────────────────────

def state_s3_key(ticket):
    """S3 object key for a ticket's state file."""
    return f"state/{ticket}_downtime.json"


def load_state(ticket):
    """
    Fetch state from S3.  If the object does not exist yet, return a blank
    default state.  The bucket is versioned, so every put creates a new
    version automatically.
    """
    s3  = _s3_client()
    key = state_s3_key(ticket)

    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=key)
        state    = json.loads(response["Body"].read().decode("utf-8"))
        version  = response.get("VersionId", "n/a")
        print(f"  State fetched ← s3://{S3_BUCKET}/{key}  (version: {version})")
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            print(f"  No existing state in S3 — starting fresh.")
            state = {
                "ticket": ticket,
                "muting_rules": {"app": [], "admin": [], "sandbox": []},
                "synthetic_downtimes": {},
            }
        else:
            raise

    # Migrate old flat-list synthetic_downtimes → per-stack dict
    if isinstance(state.get("synthetic_downtimes"), list):
        old_list = state["synthetic_downtimes"]
        migrated: dict = {}
        for entry in old_list:
            monitors = entry.get("monitors", [])
            k = monitors[0]["name"] if monitors else entry.get("name", "unknown")
            migrated.setdefault(k, []).append(entry)
        state["synthetic_downtimes"] = migrated

    return state


def save_state(ticket, state):
    """
    Upload state JSON to S3.  Because the bucket is versioned, each save
    creates a new version — old versions are preserved automatically.
    """
    s3      = _s3_client()
    key     = state_s3_key(ticket)
    body    = json.dumps(state, indent=2).encode("utf-8")

    response = s3.put_object(
        Bucket      = S3_BUCKET,
        Key         = key,
        Body        = body,
        ContentType = "application/json",
    )
    version = response.get("VersionId", "n/a")
    print(f"  State saved   → s3://{S3_BUCKET}/{key}  (version: {version})")


def delete_state(ticket):
    """
    Delete the state object from S3 after a successful destroy.
    Because the bucket is versioned this inserts a delete marker; all
    previous versions remain recoverable in S3.
    """
    s3  = _s3_client()
    key = state_s3_key(ticket)

    try:
        response = s3.delete_object(Bucket=S3_BUCKET, Key=key)
        marker   = response.get("VersionId", "n/a")
        print(f"  State deleted ✗ s3://{S3_BUCKET}/{key}  (delete-marker: {marker})")
    except ClientError as exc:
        print(f"  WARNING: Could not delete state from S3: {exc}")


# ─── Duplicate Guards ─────────────────────────────────────────────────────────

def _is_duplicate_muting_rule(existing_rules, start_time, end_time):
    return any(
        r["start_time"] == start_time and r["end_time"] == end_time
        for r in existing_rules
    )


def _is_duplicate_synthetic(existing_entries, start_time, end_time):
    """Duplicate = same time window already tracked for this stack key."""
    return any(
        d["start_time"] == start_time and d["end_time"] == end_time
        for d in existing_entries
    )


# ─── GraphQL Operations ───────────────────────────────────────────────────────

def get_monitor_guids_for_stack(api_key, account_id, stack_name):
    """Return (guids, details) for a single stack name."""
    query = f"""
    {{
      actor {{
        nrql(
          accounts: [{int(account_id)}],
          query: "FROM SyntheticCheck SELECT entityGuid, monitorName \
                  WHERE entityGuid IS NOT NULL AND monitorName IS NOT NULL \
                  AND type IN ('API_TEST','SIMPLE','STEP_MONITOR','SCRIPT_API','SCRIPT_BROWSER') \
                  SINCE 1 hour ago LIMIT MAX"
        ) {{
          results
        }}
      }}
    }}
    """
    result = execute_graphql(api_key, query)

    if result.get("errors"):
        raise RuntimeError(f"Failed to fetch monitors: {result['errors']}")

    rows = result.get("data", {}).get("actor", {}).get("nrql", {}).get("results", [])

    seen = set()
    all_monitors = []
    for item in rows:
        guid = item.get("entityGuid")
        name = item.get("monitorName", "")
        if guid and guid not in seen:
            seen.add(guid)
            all_monitors.append({"guid": guid, "name": name})

    stack_lower = stack_name.lower()
    guids   = []
    details = []
    for monitor in all_monitors:
        if stack_lower in monitor["name"].lower():
            guids.append(monitor["guid"])
            details.append({"name": monitor["name"], "guid": monitor["guid"]})
            print(f"    ✔ {monitor['name']}  ({monitor['guid']})")

    if not guids:
        print(f"    ✘ No monitors found for stack '{stack_name}'")

    return guids, details


def create_synthetic_downtime(api_key, account_id, name, start_time, end_time, monitor_guids):
    guid_str = ", ".join(f'"{g}"' for g in monitor_guids if g)
    mutation = f"""
    mutation {{
      syntheticsCreateOnceMonitorDowntime(
        accountId: {account_id},
        name: "{name}",
        monitorGuids: [{guid_str}],
        timezone: "{TIMEZONE}",
        startTime: "{start_time}",
        endTime: "{end_time}"
      ) {{
        guid name accountId monitorGuids timezone startTime endTime
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def destroy_synthetic_downtime(api_key, downtime_guid):
    mutation = f"""
    mutation {{
      syntheticsDeleteMonitorDowntime(guid: "{downtime_guid}") {{
        guid
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def create_muting_rule(api_key, account_id, name, start_time, end_time, condition_ids):
    conditions_str = ",".join(
        f'{{ attribute: "conditionId", operator: EQUALS, values: "{cid}" }}'
        for cid in condition_ids
    )
    mutation = f"""
    mutation {{
      alertsMutingRuleCreate(
        accountId: {account_id}
        rule: {{
          condition: {{
            conditions: [{conditions_str}]
            operator: OR
          }}
          enabled: true
          name: "{name}"
          schedule: {{
            startTime: "{start_time}"
            endTime: "{end_time}"
            timeZone: "{TIMEZONE}"
          }}
        }}
      ) {{
        id name enabled
        condition {{ operator }}
        schedule {{ startTime endTime timeZone }}
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def destroy_muting_rule(api_key, account_id, rule_id):
    mutation = f"""
    mutation {{
      alertsMutingRuleDelete(accountId: {account_id}, id: {rule_id}) {{
        id
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


# ─── Apply / Destroy ──────────────────────────────────────────────────────────

def apply_downtime(api_key, account_id, ticket, start_dt, end_dt, stack_names, environments):
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  APPLY DOWNTIME — {ticket}")
    print(f"  Stacks       : {stack_names}")
    print(f"  Environments : {environments}")
    print(f"  Window       : {start_dt}  →  {end_dt}")
    print(f"{sep}\n")

    state = load_state(ticket)

    # ── 1. One Synthetic Downtime per Stack ──────────────────────────────────
    print("[ Synthetic Downtimes — per stack ]")
    synthetic_map = state.setdefault("synthetic_downtimes", {})

    for stack in stack_names:
        stack_key = stack.strip().lower().replace(" ", "-").replace("_", "-")
        print(f"\n  Stack: {stack}")

        existing_entries = synthetic_map.setdefault(stack_key, [])

        if _is_duplicate_synthetic(existing_entries, start_dt, end_dt):
            print("  Duplicate detected (same window) — skipping.")
            continue

        monitor_guids, monitor_details = get_monitor_guids_for_stack(
            api_key, account_id, stack
        )

        if not monitor_guids:
            print(f"  No monitors matched for '{stack}' — skipping synthetic downtime.")
            continue

        name = f"{ticket} - TCP Production Synthetic Monitor Downtime ({stack})"
        print(f"  Creating: {name}")
        result = create_synthetic_downtime(
            api_key, account_id, name, start_dt, end_dt, monitor_guids
        )

        if result.get("errors"):
            print(f"  ERROR: {result['errors']}")
            sys.exit(1)

        rd = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime", {})
        if not rd.get("guid"):
            print("  ERROR: No GUID returned for synthetic downtime.")
            sys.exit(1)

        existing_entries.append({
            "id": rd["guid"],
            "name": name,
            "monitors": monitor_details,
            "start_time": start_dt,
            "end_time": end_dt,
        })
        print(f"  ✔ Created  GUID: {rd['guid']}")

    print()

    # ── 2. One Muting Rule per Environment ───────────────────────────────────
    for env in environments:
        cfg = ENVIRONMENT_CONFIG.get(env)
        if not cfg:
            print(f"[ {env} ] Unknown environment — skipping.")
            continue

        key           = cfg["key"]
        condition_ids = cfg["condition_ids"]
        rule_name     = f"{ticket} - {cfg['label']}"

        print(f"[ Muting Rule — {env} ]")

        existing = state["muting_rules"].setdefault(key, [])
        if _is_duplicate_muting_rule(existing, start_dt, end_dt):
            print("  Duplicate detected (same window) — skipping.\n")
            continue

        print(f"  Creating: {rule_name}")
        result = create_muting_rule(api_key, account_id, rule_name, start_dt, end_dt, condition_ids)

        if result.get("errors"):
            print(f"  ERROR: {result['errors'][0].get('message', result['errors'])}\n")
            continue

        rd = result.get("data", {}).get("alertsMutingRuleCreate", {})
        if rd and rd.get("id"):
            rule_id = str(rd["id"])
            existing.append({
                "id": rule_id,
                "name": rule_name,
                "condition_ids": condition_ids,
                "start_time": start_dt,
                "end_time": end_dt,
            })
            print(f"  ✔ Created  ID: {rule_id}\n")
        else:
            print("  WARNING: Muting rule created but no ID returned.\n")

    save_state(ticket, state)
    print("Downtime application complete.")


def destroy_downtime(api_key, account_id, ticket):
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  DESTROY DOWNTIME — {ticket}")
    print(f"{sep}\n")

    state = load_state(ticket)

    # ── Synthetic Downtimes (per stack) ──────────────────────────────────────
    synthetic_map = state.get("synthetic_downtimes", {})
    if not synthetic_map:
        print("[ Synthetic Downtimes ]\n  None found.\n")
    else:
        for stack_key, entries in synthetic_map.items():
            if not entries:
                continue
            print(f"[ Synthetic Downtimes — {stack_key} ]")
            for item in entries:
                guid = item.get("id")
                if not guid:
                    continue
                print(f"  Deleting: {item.get('name', guid)}")
                result = destroy_synthetic_downtime(api_key, guid)
                if result.get("errors"):
                    print(f"  ERROR: {result['errors']}")
                else:
                    print(f"  ✔ Deleted  GUID: {guid}")
            print()

    # ── Muting Rules ─────────────────────────────────────────────────────────
    for env_key, rules in state.get("muting_rules", {}).items():
        if not rules:
            continue
        print(f"[ Muting Rules — {env_key} ]")
        for rule in rules:
            rule_id = rule.get("id")
            if not rule_id:
                continue
            print(f"  Deleting: {rule.get('name', rule_id)}")
            result = destroy_muting_rule(api_key, account_id, rule_id)
            if result.get("errors"):
                print(f"  ERROR: {result['errors']}")
            else:
                print(f"  ✔ Deleted  ID: {rule_id}")
        print()

    # ── Remove state from S3 ─────────────────────────────────────────────────
    delete_state(ticket)
    print("\nDowntime destruction complete.")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 5:
        print("Usage:")
        print("  apply:   python3 downtime.py <api_key> <account_id> apply <ticket> "
              "<start_date> <start_time> <end_date> <end_time> <stacks_csv> <environments_csv>")
        print("  destroy: python3 downtime.py <api_key> <account_id> destroy <ticket>")
        sys.exit(1)

    api_key    = sys.argv[1]
    account_id = sys.argv[2]
    action     = sys.argv[3]
    ticket     = sys.argv[4]

    if action == "apply":
        if len(sys.argv) < 11:
            print("Insufficient arguments for apply.")
            sys.exit(1)

        start_date   = sys.argv[5]
        start_time   = sys.argv[6]
        end_date     = sys.argv[7]
        end_time     = sys.argv[8]
        stacks_csv   = sys.argv[9]
        envs_csv     = sys.argv[10] if len(sys.argv) > 10 else ""

        start_dt     = f"{start_date}T{start_time}"
        end_dt       = f"{end_date}T{end_time}"
        stack_names  = [s.strip() for s in stacks_csv.split(",") if s.strip()]
        environments = [e.strip() for e in envs_csv.split(",")   if e.strip()]

        apply_downtime(api_key, account_id, ticket, start_dt, end_dt, stack_names, environments)

    elif action == "destroy":
        destroy_downtime(api_key, account_id, ticket)

    else:
        print(f"Unknown action: '{action}'. Use 'apply' or 'destroy'.")
        sys.exit(1)


if __name__ == "__main__":
    main()

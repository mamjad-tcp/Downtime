import json
import os
import sys

import boto3
import requests
from botocore.exceptions import ClientError

ENDPOINT = "https://api.newrelic.com/graphql"
TIMEZONE = "America/Chicago"

# ─── S3 Configuration ─────────────────────────────────────────────────────────
# Replace these placeholders with your actual values.
# Jenkins IAM role/user must have the following S3 permissions:
#   - s3:GetObject
#   - s3:PutObject
#   - s3:DeleteObject
#   - s3:ListBucket       (needed to check object existence)
#
# Recommended IAM policy (attach to the Jenkins role/user):
#
#   {
#     "Version": "2012-10-17",
#     "Statement": [
#       {
#         "Effect": "Allow",
#         "Action": [
#           "s3:GetObject",
#           "s3:PutObject",
#           "s3:DeleteObject"
#         ],
#         "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/downtime/*"
#       },
#       {
#         "Effect": "Allow",
#         "Action": "s3:ListBucket",
#         "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME",
#         "Condition": {
#           "StringLike": { "s3:prefix": ["downtime/*"] }
#         }
#       }
#     ]
#   }

S3_BUCKET_NAME = "YOUR-BUCKET-NAME"          # e.g. "tcp-devops-downtime-state"
S3_KEY_PREFIX  = "downtime"                  # top-level folder inside the bucket
AWS_REGION     = "us-east-1"                 # e.g. "us-east-1" — match your bucket region

# Final S3 key pattern → downtime/{ticket}/{ticket}_downtime.json


# ─── Condition IDs live here, not in Jenkins ──────────────────────────────────
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


# ─── General Helpers ─────────────────────────────────────────────────────────

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


# ─── S3 State Management ──────────────────────────────────────────────────────

def _s3_client():
    """Return a boto3 S3 client.
    
    Credentials are automatically resolved in this order by boto3:
      1. IAM role attached to the Jenkins EC2 instance (recommended — no keys needed)
      2. Environment variables AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
      3. ~/.aws/credentials file on the Jenkins agent

    No code changes are needed here when using an IAM role — just attach the
    role to the EC2 instance and boto3 picks it up automatically.
    """
    return boto3.client("s3", region_name=AWS_REGION)


def _s3_key(ticket):
    """Build the full S3 object key for a given ticket.
    
    Pattern: downtime/{ticket}/{ticket}_downtime.json
    Example: downtime/DEVOPS-12345/DEVOPS-12345_downtime.json
    """
    return f"{S3_KEY_PREFIX}/{ticket}/{ticket}_downtime.json"


def save_state_to_s3(ticket, state):
    """Upload the downtime state JSON to S3.

    Called after every apply operation so the state is persisted centrally
    and is accessible by any Jenkins agent (no local file dependency).

    S3 path:  s3://{S3_BUCKET_NAME}/downtime/{ticket}/{ticket}_downtime.json

    Required IAM permissions on the Jenkins role/user:
      - s3:PutObject  on  arn:aws:s3:::{S3_BUCKET_NAME}/downtime/*

    Args:
        ticket (str): Ticket identifier, e.g. "DEVOPS-12345".
        state  (dict): The full downtime state dictionary to persist.

    Raises:
        SystemExit: If the upload fails.
    """
    key     = _s3_key(ticket)
    payload = json.dumps(state, indent=2).encode("utf-8")

    try:
        s3 = _s3_client()
        s3.put_object(
            Bucket      = S3_BUCKET_NAME,
            Key         = key,
            Body        = payload,
            ContentType = "application/json",
        )
        print(f"  State saved → s3://{S3_BUCKET_NAME}/{key}")
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        print(f"  ERROR saving state to S3 [{error_code}]: {exc}")
        sys.exit(1)


def load_state_from_s3(ticket):
    """Download and return the downtime state JSON from S3.

    If no state file exists for the ticket yet (fresh run), an empty
    skeleton is returned so the rest of the code can proceed normally.

    S3 path:  s3://{S3_BUCKET_NAME}/downtime/{ticket}/{ticket}_downtime.json

    Required IAM permissions on the Jenkins role/user:
      - s3:GetObject   on  arn:aws:s3:::{S3_BUCKET_NAME}/downtime/*
      - s3:ListBucket  on  arn:aws:s3:::{S3_BUCKET_NAME}
                           (with prefix condition "downtime/*")

    Args:
        ticket (str): Ticket identifier, e.g. "DEVOPS-12345".

    Returns:
        dict: Existing state from S3, or a fresh empty skeleton if not found.
    """
    key = _s3_key(ticket)

    try:
        s3       = _s3_client()
        response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        body     = response["Body"].read().decode("utf-8")
        state    = json.loads(body)
        print(f"  State loaded ← s3://{S3_BUCKET_NAME}/{key}")
        return state
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchKey":
            # First run for this ticket — return an empty skeleton
            print(f"  No existing state found in S3 for ticket '{ticket}'. Starting fresh.")
            return {
                "ticket": ticket,
                "muting_rules": {"app": [], "admin": [], "sandbox": []},
                "synthetic_downtimes": [],
            }
        # Any other S3 error (permissions, bucket missing, etc.) is fatal
        print(f"  ERROR loading state from S3 [{error_code}]: {exc}")
        sys.exit(1)


def delete_state_from_s3(ticket):
    """Delete the downtime state JSON from S3 after a successful destroy.

    Called at the end of destroy_downtime() once all NewRelic resources have
    been removed so the S3 object doesn't linger as stale data.

    S3 path:  s3://{S3_BUCKET_NAME}/downtime/{ticket}/{ticket}_downtime.json

    Required IAM permissions on the Jenkins role/user:
      - s3:DeleteObject  on  arn:aws:s3:::{S3_BUCKET_NAME}/downtime/*

    Args:
        ticket (str): Ticket identifier, e.g. "DEVOPS-12345".
    """
    key = _s3_key(ticket)

    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
        print(f"  State deleted ✔ s3://{S3_BUCKET_NAME}/{key}")
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        # A missing key on delete is not an error — already gone
        if error_code == "NoSuchKey":
            print(f"  State file not found in S3 (already deleted or never created).")
        else:
            print(f"  WARNING: Could not delete state from S3 [{error_code}]: {exc}")
            # Non-fatal — destruction of NewRelic resources already succeeded


# ─── Deduplication Helpers ───────────────────────────────────────────────────

def _is_duplicate_muting_rule(existing_rules, start_time, end_time):
    return any(
        r["start_time"] == start_time and r["end_time"] == end_time
        for r in existing_rules
    )


def _is_duplicate_synthetic(existing, start_time, end_time, monitor_guids):
    target = set(monitor_guids)
    return any(
        d["start_time"] == start_time
        and d["end_time"] == end_time
        and set(d.get("monitor_guids", [])) == target
        for d in existing
    )


# ─── GraphQL Operations ───────────────────────────────────────────────────────

def get_monitor_guids(api_key, account_id, stack_names):
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

    all_monitors = []
    seen = set()
    for item in rows:
        guid = item.get("entityGuid")
        name = item.get("monitorName", "")
        if guid and guid not in seen:
            seen.add(guid)
            all_monitors.append({"guid": guid, "name": name})

    guids   = []
    details = []
    matched = set()

    for stack in stack_names:
        stack_lower = stack.lower()
        found = False
        for monitor in all_monitors:
            if stack_lower in monitor["name"].lower() and monitor["guid"] not in matched:
                matched.add(monitor["guid"])
                guids.append(monitor["guid"])
                details.append({"name": monitor["name"], "guid": monitor["guid"]})
                print(f"    ✔ {monitor['name']}  ({monitor['guid']})")
                found = True
        if not found:
            print(f"    ✘ No monitors found for stack '{stack}'")

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

    # Load existing state from S3 (or fresh skeleton if first run)
    state = load_state_from_s3(ticket)

    # ── 1. Synthetic Downtime ─────────────────────────────────────────────────
    print("[ Synthetic Downtime ]")
    monitor_guids, monitor_details = get_monitor_guids(api_key, account_id, stack_names)

    if not monitor_guids:
        print("  No monitors matched — skipping synthetic downtime.\n")
    elif _is_duplicate_synthetic(state["synthetic_downtimes"], start_dt, end_dt, monitor_guids):
        print("  Duplicate detected (same window + monitors) — skipping.\n")
    else:
        stack_suffix = build_stack_suffix(stack_names)
        name = f"{ticket} - TCP Production Synthetic Monitor Downtime ({stack_suffix})"
        print(f"  Creating: {name}")
        result = create_synthetic_downtime(api_key, account_id, name, start_dt, end_dt, monitor_guids)

        if result.get("errors"):
            print(f"  ERROR: {result['errors']}")
            sys.exit(1)

        rd = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime", {})
        if not rd.get("guid"):
            print("  ERROR: No GUID returned for synthetic downtime.")
            sys.exit(1)

        state["synthetic_downtimes"].append({
            "id": rd["guid"],
            "name": name,
            "monitors": monitor_details,
            "monitor_guids": monitor_guids,
            "start_time": start_dt,
            "end_time": end_dt,
        })
        print(f"  ✔ Created  GUID: {rd['guid']}\n")

    # ── 2. One Muting Rule per Environment ────────────────────────────────────
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
            print(f"  Duplicate detected (same window) — skipping.\n")
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

    # Persist updated state back to S3
    save_state_to_s3(ticket, state)
    print("Downtime application complete.")


def destroy_downtime(api_key, account_id, ticket):
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  DESTROY DOWNTIME — {ticket}")
    print(f"{sep}\n")

    # Load state from S3
    state = load_state_from_s3(ticket)

    # ── Synthetic Downtimes ───────────────────────────────────────────────────
    print("[ Synthetic Downtimes ]")
    synthetic_list = state.get("synthetic_downtimes", [])
    if not synthetic_list:
        print("  None found.\n")
    else:
        for item in synthetic_list:
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

    # ── Muting Rules ──────────────────────────────────────────────────────────
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

    # Remove state from S3 — all NewRelic resources have been cleaned up
    delete_state_from_s3(ticket)
    print("\nDowntime destruction complete.")


# ─── Entry Point ─────────────────────────────────────────────────────────────

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
import json
import os
import sys

import requests

ENDPOINT = "https://api.newrelic.com/graphql"
TIMEZONE = "America/Chicago"

def build_stack_suffix(stack_names):
    cleaned = []
    for stack in stack_names:
        value = stack.strip().replace(" ", "-").replace("_", "-")
        if value:
            cleaned.append(value)
    return "-".join(cleaned)
    
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


def append_unique_line(filename, value):
    existing_values = set()

    if os.path.exists(filename):
        with open(filename, "r") as file_handle:
            existing_values = {
                line.strip() for line in file_handle.readlines() if line.strip()
            }

    if value not in existing_values:
        with open(filename, "a") as file_handle:
            file_handle.write(f"{value}\n")


def append_unique_lines(filename, values):
    existing_values = set()

    if os.path.exists(filename):
        with open(filename, "r") as file_handle:
            existing_values = {
                line.strip() for line in file_handle.readlines() if line.strip()
            }

    new_values = [value for value in values if value and value not in existing_values]

    if new_values:
        with open(filename, "a") as file_handle:
            for value in new_values:
                file_handle.write(f"{value}\n")


def load_lines(filename):
    if not os.path.exists(filename):
        return []

    with open(filename, "r") as file_handle:
        return [line.strip() for line in file_handle.readlines() if line.strip()]


def remove_file_if_exists(filename):
    if os.path.exists(filename):
        os.remove(filename)


def save_synthetic_downtime_id(ticket, downtime_guid):
    filename = f"{ticket}_synthetic_downtime_id.txt"
    append_unique_line(filename, downtime_guid)
    print(f"Saved synthetic downtime GUID to {filename}")


def load_synthetic_downtime_ids(ticket):
    filename = f"{ticket}_synthetic_downtime_id.txt"
    return load_lines(filename)


def save_muting_rule_ids(ticket, muting_rule_ids):
    filename = f"{ticket}_muting_rules_id.txt"
    append_unique_lines(filename, muting_rule_ids)
    print(f"Saved {len(muting_rule_ids)} muting rule ID(s) to {filename}")


def load_muting_rule_ids(ticket):
    filename = f"{ticket}_muting_rules_id.txt"
    return load_lines(filename)


def get_monitor_guids(api_key, account_id, stack_names):
    query = f"""
    {{
      actor {{
        nrql(
          accounts: [{int(account_id)}],
          query: "FROM SyntheticCheck SELECT entityGuid, monitorName WHERE entityGuid IS NOT NULL AND monitorName IS NOT NULL AND type IN ('API_TEST', 'SIMPLE', 'STEP_MONITOR', 'SCRIPT_API', 'SCRIPT_BROWSER') SINCE 1 hour ago LIMIT MAX"
        ) {{
          results
        }}
      }}
    }}
    """

    result = execute_graphql(api_key, query)

    if result.get("errors"):
        raise RuntimeError(f"Failed to fetch monitors: {result['errors']}")

    results = result.get("data", {}).get("actor", {}).get("nrql", {}).get("results", [])

    all_monitors = []
    seen_guids = set()

    for item in results:
        entity_guid = item.get("entityGuid")
        monitor_name = item.get("monitorName")

        if entity_guid and entity_guid not in seen_guids:
            seen_guids.add(entity_guid)
            all_monitors.append({
                "guid": entity_guid,
                "name": monitor_name or "",
            })

    monitor_guids = []
    matched_guid_set = set()

    for stack_name in stack_names:
        stack_lower = stack_name.lower()
        stack_matches = []

        for monitor in all_monitors:
            monitor_name = monitor["name"].lower()
            monitor_guid = monitor["guid"]

            if stack_lower in monitor_name:
                stack_matches.append((monitor_guid, monitor["name"]))

        if stack_matches:
            print(f"Matched monitors for stack '{stack_name}':")
            for guid, name in stack_matches:
                print(f"  {name} ({guid})")
                if guid not in matched_guid_set:
                    matched_guid_set.add(guid)
                    monitor_guids.append(guid)
        else:
            print(f"No monitors found for stack '{stack_name}'")

    return monitor_guids


def create_synthetic_downtime(api_key, account_id, name, start_time, end_time, monitor_guids):
    guid_string = ", ".join([f'"{guid.strip()}"' for guid in monitor_guids if guid.strip()])

    mutation = f"""
    mutation {{
      syntheticsCreateOnceMonitorDowntime(
        accountId: {account_id},
        name: "{name}",
        monitorGuids: [{guid_string}],
        timezone: "{TIMEZONE}",
        startTime: "{start_time}",
        endTime: "{end_time}"
      ) {{
        guid
        accountId
        name
        monitorGuids
        timezone
        startTime
        endTime
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def destroy_synthetic_downtime(api_key, downtime_guid):
    mutation = f"""
    mutation {{
      syntheticsDeleteMonitorDowntime(
        guid: "{downtime_guid}"
      ) {{
        guid
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def create_muting_rule(api_key, account_id, name, start_time, end_time, timezone, condition_ids):
    conditions_array = []
    for condition_id in condition_ids:
        conditions_array.append(
            f"""
        {{
          attribute: "conditionId"
          operator: EQUALS
          values: "{condition_id}"
        }}
        """
        )

    conditions_str = ",".join(conditions_array)

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
            timeZone: "{timezone}"
          }}
        }}
      ) {{
        id
        name
        enabled
        condition {{
          operator
        }}
        schedule {{
          startTime
          endTime
          timeZone
        }}
      }}
    }}
    """
    return execute_graphql(api_key, mutation)


def destroy_muting_rule(api_key, account_id, muting_rule_id):
    mutation = f"""
    mutation {{
      alertsMutingRuleDelete(
        accountId: {account_id}
        id: {muting_rule_id}
      ) {{
        id
      }}
    }}
    """
    return execute_graphql(api_key, mutation)

def apply_downtime(api_key, account_id, ticket, start_datetime, end_datetime, stack_names, condition_ids):
    print(f"Creating downtime for ticket: {ticket}")
    print(f"Stacks: {stack_names}")
    print(f"Condition IDs: {condition_ids}")
    print(f"Start: {start_datetime}")
    print(f"End: {end_datetime}")

    monitor_guids = get_monitor_guids(api_key, account_id, stack_names)
    if not monitor_guids:
        print("No monitor GUIDs found. Aborting downtime creation.")
        sys.exit(1)

    stack_suffix = build_stack_suffix(stack_names)

    downtime_name = f"{ticket}_{stack_suffix}_downtime"
    result = create_synthetic_downtime(
        api_key,
        account_id,
        downtime_name,
        start_datetime,
        end_datetime,
        monitor_guids,
    )

    errors = result.get("errors")
    if errors:
        print(f"Error creating downtime: {errors}")
        sys.exit(1)

    response_data = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime")
    if not response_data or not response_data.get("guid"):
        print("Downtime creation finished, but no GUID was returned.")
        sys.exit(1)

    downtime_guid = response_data["guid"]
    print(f"Downtime created successfully: {downtime_guid}")
    save_synthetic_downtime_id(ticket, downtime_guid)

    if not condition_ids:
        print("No condition IDs provided. Skipping muting rule creation.")
        return

    muting_rule_name = f"{ticket}_{stack_suffix}_muting_rule"
    result = create_muting_rule(
        api_key,
        account_id,
        muting_rule_name,
        start_datetime,
        end_datetime,
        TIMEZONE,
        condition_ids,
    )

    errors = result.get("errors")
    if errors:
        error_message = errors[0].get("message", "Unknown error")
        print(f"Error creating muting rule: {error_message}")
        return

    response_data = result.get("data", {}).get("alertsMutingRuleCreate")
    if response_data and response_data.get("id"):
        muting_rule_id = str(response_data["id"])
        print(f"Muting rule created successfully: {muting_rule_id}")
        save_muting_rule_ids(ticket, [muting_rule_id])
        
def destroy_downtime(api_key, account_id, ticket):
    print(f"Destroying downtime for ticket: {ticket}")

    downtime_file = f"{ticket}_synthetic_downtime_id.txt"
    muting_rule_file = f"{ticket}_muting_rules_id.txt"

    downtime_guids = load_synthetic_downtime_ids(ticket)
    if downtime_guids:
        for downtime_guid in downtime_guids:
            print(f"Destroying synthetic downtime: {downtime_guid}")
            result = destroy_synthetic_downtime(api_key, downtime_guid)

            errors = result.get("errors")
            if errors:
                print(f"Error destroying synthetic downtime {downtime_guid}: {errors}")
            else:
                print(f"Synthetic downtime destroyed successfully: {downtime_guid}")

        remove_file_if_exists(downtime_file)
    else:
        print(f"No synthetic downtime GUIDs found for ticket: {ticket}")

    muting_rule_ids = load_muting_rule_ids(ticket)
    if muting_rule_ids:
        for muting_rule_id in muting_rule_ids:
            print(f"Destroying muting rule: {muting_rule_id}")
            result = destroy_muting_rule(api_key, account_id, muting_rule_id)

            errors = result.get("errors")
            if errors:
                print(f"Error destroying muting rule {muting_rule_id}: {errors}")
            else:
                print(f"Muting rule destroyed successfully: {muting_rule_id}")

        remove_file_if_exists(muting_rule_file)
    else:
        print(f"No muting rule IDs found for ticket: {ticket}")


def main():
    if len(sys.argv) < 5:
        print("Usage:")
        print("  apply:   python3 downtime.py <api_key> <account_id> apply <ticket> <start_date> <start_time> <end_date> <end_time> <stacks_name> <muting_environment> [condition_ids]")
        print("  destroy: python3 downtime.py <api_key> <account_id> destroy <ticket>")
        sys.exit(1)

    api_key = sys.argv[1]
    account_id = sys.argv[2]
    condition = sys.argv[3]
    ticket = sys.argv[4]

    if condition == "apply":
        if len(sys.argv) < 11:
            print("Insufficient arguments for apply")
            sys.exit(1)

        start_date = sys.argv[5]
        start_time = sys.argv[6]
        end_date = sys.argv[7]
        end_time = sys.argv[8]
        stacks_name = sys.argv[9]
        condition_ids = sys.argv[11] if len(sys.argv) > 11 else ""

        start_datetime = f"{start_date}T{start_time}"
        end_datetime = f"{end_date}T{end_time}"
        stack_names = [item.strip() for item in stacks_name.split(",") if item.strip()]
        condition_ids_list = [item.strip() for item in condition_ids.split(",") if item.strip()]

        apply_downtime(
            api_key,
            account_id,
            ticket,
            start_datetime,
            end_datetime,
            stack_names,
            condition_ids_list,
        )
    elif condition == "destroy":
        destroy_downtime(api_key, account_id, ticket)
    else:
        print(f"Unknown condition: {condition}. Use 'apply' or 'destroy'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
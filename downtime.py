import requests
import json
import sys
import os

ENDPOINT = "https://api.newrelic.com/graphql"
SYNTHETICS_ENDPOINT = "https://synthetics.newrelic.com/synthetics/api/v3/monitors"


def execute_graphql(api_key, query):
    headers = {
        "Content-Type": "application/json",
        "API-Key": api_key
    }
    response = requests.post(
        ENDPOINT,
        headers=headers,
        json={"query": query},
        timeout=60
    )
    response.raise_for_status()
    return response.json()


# ---------------- FILE UTILITIES ----------------
def save_synthetic_downtime_id(ticket, downtime_guid):
    """Append synthetic downtime GUID to file if not already present"""
    filename = f"{ticket}_synthetic_downtime_id.txt"
    existing_ids = set()

    if os.path.exists(filename):
        with open(filename, 'r') as f:
            existing_ids = {line.strip() for line in f.readlines() if line.strip()}

    if downtime_guid not in existing_ids:
        with open(filename, 'a') as f:
            f.write(f"{downtime_guid}\n")
        print(f"Appended synthetic downtime GUID to {filename}")
    else:
        print(f"Synthetic downtime GUID already present in {filename}")


def load_synthetic_downtime_id(ticket):
    """Load synthetic downtime GUID from file"""
    filename = f"{ticket}_synthetic_downtime_id.txt"
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return f.read().strip()
    return None


def save_muting_rule_ids(ticket, muting_rule_ids):
    """Append muting rule IDs to file instead of overwriting"""
    filename = f"{ticket}_muting_rules_id.txt"
    with open(filename, 'a') as f:
        for rule_id in muting_rule_ids:
            f.write(f"{rule_id}\n")
    print(f"Appended {len(muting_rule_ids)} muting rule IDs to {filename}")


def load_muting_rule_ids(ticket):
    """Load muting rule IDs from file"""
    filename = f"{ticket}_muting_rules_id.txt"
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    return []


def get_monitor_guids(api_key, account_id, stack_names):
    """
    Fetch monitor EntityGUIDs from New Relic NRQL query based on stack names.

    Args:
        api_key: NewRelic API key
        account_id: NewRelic account ID
        stack_names: List of stack names to search for

    Returns:
        List of monitor EntityGUIDs that match the stack names
    """
    monitor_guids = []
    all_monitors = []

    print("Fetching monitor EntityGUIDs from New Relic using NRQL query...")

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

    try:
        result = execute_graphql(api_key, query)

        if result.get("errors"):
            print(f"GraphQL Error: {result.get('errors')}")
            raise Exception("Failed to fetch monitors from NRQL query")

        results = result.get("data", {}).get("actor", {}).get("nrql", {}).get("results", [])

        print(f"Total results from NRQL query: {len(results)}")
        print("Raw NRQL results:")
        print(json.dumps(results, indent=2))

        # Process results and deduplicate by entity GUID
        seen_guids = set()
        for item in results:
            entity_guid = item.get("entityGuid")
            monitor_name = item.get("monitorName")

            if entity_guid and entity_guid not in seen_guids:
                seen_guids.add(entity_guid)
                all_monitors.append({
                    "guid": entity_guid,
                    "name": monitor_name
                })

        print(f"Total unique monitors found: {len(all_monitors)}")
        print("All monitors fetched from New Relic:")
        for monitor in all_monitors:
            name = monitor.get("name") or "<no-name>"
            guid = monitor.get("guid") or "<no-guid>"
            print(f"  - {name} (EntityGUID: {guid})")

        # Filter monitors by stack names
        print(f"Filtering monitors by stack names: {stack_names}")

        for stack_name in stack_names:
            stack_lower = stack_name.lower()
            matched_monitors = []

            for monitor in all_monitors:
                monitor_name = (monitor.get("name") or "").lower()
                monitor_guid = monitor.get("guid")

                if stack_lower in monitor_name:
                    matched_monitors.append((monitor_guid, monitor.get("name")))

            if matched_monitors:
                print(f"Stack '{stack_name}' matched {len(matched_monitors)} monitor(s):")
                for guid, name in matched_monitors:
                    print(f"  - {name} (EntityGUID: {guid})")
                    monitor_guids.append(guid)
            else:
                print(f"Warning: No monitors found for stack '{stack_name}'")

        if not monitor_guids:
            print("Error: No monitor EntityGUIDs found for any of the specified stacks")
            return []

        print(f"Total monitor EntityGUIDs to apply downtime: {len(monitor_guids)}")
        return monitor_guids

    except Exception as e:
        print(f"Error fetching monitors: {e}")
        return []
# ---------------- CREATE ----------------
def create_synthetic_downtime(api_key, account_id, name, start_time, end_time, monitor_guids):

    guid_string = ', '.join([f'"{g.strip()}"' for g in monitor_guids if g.strip()])

    # Format: convert "yyyy-MM-dd HH:mm:ss" to "yyyy-MM-ddTHH:mm:ss"
    start_time = start_time.replace(' ', 'T')
    end_time = end_time.replace(' ', 'T')

    mutation = f"""
    mutation {{
      syntheticsCreateOnceMonitorDowntime(
        accountId: {account_id},
        name: "{name}",
        monitorGuids: [{guid_string}],
        timezone: "America/Chicago",
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


# ---------------- DESTROY (NOW GUID BASED) ----------------
def destroy_synthetic_downtime(api_key, account_id, downtime_guid):

    print("inside destroy synthetic downtime")

    mutation = f"""
    mutation {{
      syntheticsDeleteMonitorDowntime(
        guid: "{downtime_guid}"
      ) {{
        guid
      }}
    }}
    """

    result = execute_graphql(api_key, mutation)
    print("Delete result:", json.dumps(result, indent=2))
    return result


def create_muting_rule(api_key, account_id, name, start_time, end_time, timezone, condition_names):
    """
    Create a muting rule with schedule and conditions.
    
    Args:
        api_key: NewRelic API key
        account_id: Account ID
        name: Name of the muting rule
        start_time: Start time in format "yyyy-MM-ddTHH:mm:ss"
        end_time: End time in format "yyyy-MM-ddTHH:mm:ss"
        timezone: Timezone (e.g., "America/Chicago")
        condition_names: List of condition names to mute
    """
    
    # Build condition objects for each condition name
    conditions_array = []
    for condition_name in condition_names:
        conditions_array.append(f'''
        {{
          attribute: "conditionId"
          operator: EQUALS
          values: "{condition_name}"
        }}
        ''')
    
    conditions_str = ','.join(conditions_array)
    
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

    result = execute_graphql(api_key, mutation)
    print("Delete result:", json.dumps(result, indent=2))
    return result


# ---------------- MAIN ----------------
if __name__ == "__main__":

    api_key = sys.argv[1]
    account_id = sys.argv[2]
    condition = sys.argv[3]  # 'apply' or 'destroy'
    ticket = sys.argv[4]

    if condition == "apply":
        # Arguments: api_key, account_id, condition, ticket, start_date, start_time, end_date, end_time, stacks_name, muting_environment, condition_ids
        start_date = sys.argv[5]
        start_time = sys.argv[6]
        end_date = sys.argv[7]
        end_time = sys.argv[8]
        stacks_name = sys.argv[9]  # comma-separated list
        muting_environment = sys.argv[10]  # comma-separated list (for logging)
        condition_ids = sys.argv[11] if len(sys.argv) > 11 else ""  # comma-separated list of condition IDs

        # Combine date and time in format: yyyy-MM-ddTHH:mm:ss
        start_datetime = f"{start_date}T{start_time}"
        end_datetime = f"{end_date}T{end_time}"

        # Parse stack names
        stack_names = [s.strip() for s in stacks_name.split(",") if s.strip()]
        
        # Parse muting environments for logging
        muting_envs = [m.strip() for m in muting_environment.split(",") if m.strip()]
        
        # Parse condition IDs for muting rules
        condition_ids_list = [cid.strip() for cid in condition_ids.split(",") if cid.strip()]

        print(f"Creating downtime for ticket: {ticket}")
        print(f"Stacks: {stack_names}")
        print(f"Muting environments: {muting_envs}")
        print(f"Condition IDs: {condition_ids_list}")
        print(f"Start: {start_datetime}")
        print(f"End: {end_datetime}")

        # Fetch monitor GUIDs based on stack names
        monitor_guids = get_monitor_guids(api_key, account_id, stack_names)

        # Create synthetic downtime with fetched monitor GUIDs
        downtime_name = f"{ticket}_downtime"
        result = create_synthetic_downtime(
            api_key,
            account_id,
            downtime_name,
            start_datetime,
            end_datetime,
            monitor_guids
        )

        print("Create response debugging info:")
        print(json.dumps(result, indent=2))

        response_data = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime")
        errors = result.get("errors")

        if errors:
            print(f"Error creating downtime: {errors}")
            sys.exit(1)

        if response_data and response_data.get("guid"):
            downtime_guid = response_data.get("guid")

            print(
                f"Downtime created successfully.\n"
                f"GUID: {downtime_guid}\n"
                f"Name: {response_data.get('name')}"
            )

            # Save to file
            save_synthetic_downtime_id(ticket, downtime_guid)

        else:
            print("Downtime creation finished, but no GUID returned.")
            sys.exit(1)

        # Create muting rules
        muting_rule_ids = []
        if condition_ids_list:
            muting_rule_name = f"{ticket}_muting_rule"
            
            result = create_muting_rule(
                api_key,
                account_id,
                muting_rule_name,
                start_datetime,
                end_datetime,
                "America/Chicago",
                condition_ids_list
            )

            print(f"Muting rule creation response:")
            print(json.dumps(result, indent=2))

            response_data = result.get("data", {}).get("alertsMutingRuleCreate")
            errors = result.get("errors")

            if errors:
                error_msg = errors[0].get("message") if errors else "Unknown error"
                error_class = errors[0].get("extensions", {}).get("errorClass") if errors else ""
                print(f"Error creating muting rule: {error_msg}")
                if "ACCESS_DENIED" in str(error_class):
                    print(f"  - API key lacks permission to create muting rules")
            elif response_data and response_data.get("id"):
                muting_rule_id = response_data.get("id")
                muting_rule_ids.append(str(muting_rule_id))
                print(f"Muting rule created: {muting_rule_id}")
        else:
            print("No condition IDs provided, skipping muting rule creation")

        if muting_rule_ids:
            save_muting_rule_ids(ticket, muting_rule_ids)

    elif condition == "destroy":
        # Arguments: api_key, account_id, condition, ticket

        print(f"Destroying downtime for ticket: {ticket}")

        # Load and destroy synthetic downtime
        downtime_guid = load_synthetic_downtime_id(ticket)
        if downtime_guid:
            print(f"Destroying synthetic downtime: {downtime_guid}")
            result = destroy_synthetic_downtime(api_key, account_id, downtime_guid)
            if result.get("data"):
                print("Synthetic downtime destroyed successfully")
                # Delete the file after successful destruction
                try:
                    os.remove(f"{ticket}_synthetic_downtime_id.txt")
                except:
                    pass
        else:
            print(f"No synthetic downtime GUID found for ticket {ticket}")

        # Load and destroy muting rules
        muting_rule_ids = load_muting_rule_ids(ticket)
        if muting_rule_ids:
            for rule_id in muting_rule_ids:
                print(f"Destroying muting rule: {rule_id}")
                result = destroy_muting_rule(api_key, account_id, rule_id)
                if result.get("data"):
                    print(f"Muting rule {rule_id} destroyed successfully")
            # Delete the file after successful destruction
            try:
                os.remove(f"{ticket}_muting_rules_id.txt")
            except:
                pass
        else:
            print(f"No muting rule IDs found for ticket {ticket}")

    else:
        print(f"Unknown condition: {condition}. Use 'apply' or 'destroy'.")
        sys.exit(1)


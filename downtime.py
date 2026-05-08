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
    """Save synthetic downtime GUID to file"""
    filename = f"{ticket}_synthetic_downtime_id.txt"
    with open(filename, 'w') as f:
        f.write(downtime_guid)
    print(f"Saved synthetic downtime GUID to {filename}")


def load_synthetic_downtime_id(ticket):
    """Load synthetic downtime GUID from file"""
    filename = f"{ticket}_synthetic_downtime_id.txt"
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return f.read().strip()
    return None


def save_muting_rule_ids(ticket, muting_rule_ids):
    """Save muting rule IDs to file"""
    filename = f"{ticket}_muting_rules_id.txt"
    with open(filename, 'w') as f:
        f.write('\n'.join(muting_rule_ids))
    print(f"Saved {len(muting_rule_ids)} muting rule IDs to {filename}")


def load_muting_rule_ids(ticket):
    """Load muting rule IDs from file"""
    filename = f"{ticket}_muting_rules_id.txt"
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    return []


# ---------------- MONITOR GUID FETCHING ----------------
def get_monitor_guids(api_key, stack_names):
    """
    Fetch monitor EntityGUIDs from NewRelic GraphQL API based on stack names.
    
    Args:
        api_key: NewRelic API key
        stack_names: List of stack names to search for
    
    Returns:
        List of monitor EntityGUIDs that match the stack names
    """
    monitor_guids = []
    
    print("Fetching monitor EntityGUIDs from NewRelic GraphQL API...")
    
    # Query to fetch synthetic monitors
    query = """
    {
      actor {
        entitySearch(query: "type = 'MONITOR'") {
          results {
            entities {
              guid
              name
              type
            }
          }
        }
      }
    }
    """
    
    try:
        result = execute_graphql(api_key, query)
        
        if result.get("errors"):
            print(f"GraphQL Error: {result.get('errors')}")
            raise Exception("Failed to fetch monitors from GraphQL API")
        
        entities = result.get("data", {}).get("actor", {}).get("entitySearch", {}).get("results", {}).get("entities", [])
        
        print(f"Total monitors found: {len(entities)}")
        
        # Filter monitors by stack names
        print(f"Filtering monitors by stack names: {stack_names}")
        
        for stack_name in stack_names:
            stack_lower = stack_name.lower()
            matched_monitors = []
            
            for entity in entities:
                entity_name = entity.get("name", "").lower()
                entity_guid = entity.get("guid")
                
                if stack_lower in entity_name:
                    matched_monitors.append((entity_guid, entity.get("name")))
            
            if matched_monitors:
                print(f"Stack '{stack_name}' matched {len(matched_monitors)} monitor(s):")
                for guid, name in matched_monitors:
                    print(f"  - {name} (EntityGUID: {guid})")
                    monitor_guids.append(guid)
            else:
                print(f"Warning: No monitors found for stack '{stack_name}'")
        
        if not monitor_guids:
            print("Error: No monitor EntityGUIDs found for any of the specified stacks")
            sys.exit(1)
        
        print(f"Total monitor EntityGUIDs to apply downtime: {len(monitor_guids)}")
        return monitor_guids
        
    except Exception as e:
        print(f"Error fetching monitors: {e}")
        raise


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
        # Arguments: api_key, account_id, condition, ticket, start_date, start_time, end_date, end_time, stacks_name, muting_environment
        start_date = sys.argv[5]
        start_time = sys.argv[6]
        end_date = sys.argv[7]
        end_time = sys.argv[8]
        stacks_name = sys.argv[9]  # comma-separated list
        muting_environment = sys.argv[10]  # comma-separated list

        # Combine date and time in format: yyyy-MM-ddTHH:mm:ss
        start_datetime = f"{start_date}T{start_time}"
        end_datetime = f"{end_date}T{end_time}"

        # Parse stack names
        stack_names = [s.strip() for s in stacks_name.split(",") if s.strip()]
        
        # Parse muting environments (condition IDs mapping)
        muting_envs = [m.strip() for m in muting_environment.split(",") if m.strip()]

        print(f"Creating downtime for ticket: {ticket}")
        print(f"Stacks: {stack_names}")
        print(f"Muting environments: {muting_envs}")
        print(f"Start: {start_datetime}")
        print(f"End: {end_datetime}")

        # Fetch monitor GUIDs based on stack names
        monitor_guids = get_monitor_guids(api_key, stack_names)

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
        for env in muting_envs:
            muting_rule_name = f"{ticket}_muting_{env}"
            
            result = create_muting_rule(
                api_key,
                account_id,
                muting_rule_name,
                start_datetime,
                end_datetime,
                "America/Chicago",
                condition_ids
            )

            print(f"Muting rule creation response for '{env}':")
            print(json.dumps(result, indent=2))

            response_data = result.get("data", {}).get("alertsMutingRuleCreate")
            errors = result.get("errors")

            if errors:
                error_msg = errors[0].get("message") if errors else "Unknown error"
                error_class = errors[0].get("extensions", {}).get("errorClass") if errors else ""
                print(f"Error creating muting rule '{env}': {error_msg}")
                if "ACCESS_DENIED" in str(error_class):
                    print(f"  - API key lacks permission to create muting rules")
            elif response_data and response_data.get("id"):
                muting_rule_id = response_data.get("id")
                muting_rule_ids.append(str(muting_rule_id))
                print(f"Muting rule created: {muting_rule_id}")

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



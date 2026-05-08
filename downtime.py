import requests
import json
import sys
import os

ENDPOINT = "https://api.newrelic.com/graphql"


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


def create_muting_rule(api_key, account_id, name, condition_ids):

    condition_ids_string = ', '.join([f'"{cid.strip()}"' for cid in condition_ids if cid.strip()])

    mutation = f"""
    mutation {{
      alertsCreateMutingRule(
        accountId: {account_id},
        name: "{name}",
        conditionIds: [{condition_ids_string}]
      ) {{
        id
        name
        conditionIds
      }}
    }}
    """

    return execute_graphql(api_key, mutation)

def destroy_muting_rule(api_key, account_id, muting_rule_id):

    mutation = f"""
    mutation {{
      alertsDeleteMutingRule(
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

        # Create synthetic downtime
        downtime_name = f"{ticket}_downtime"
        result = create_synthetic_downtime(
            api_key,
            account_id,
            downtime_name,
            start_datetime,
            end_datetime,
            stack_names
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
            # Note: You need to map environments to condition IDs or get them from Jenkins
            # This is a placeholder - adjust based on your actual condition ID mappings
            result = create_muting_rule(
                api_key,
                account_id,
                muting_rule_name,
                [env]  # env should be a condition ID
            )

            print(f"Muting rule creation response:")
            print(json.dumps(result, indent=2))

            response_data = result.get("data", {}).get("alertsCreateMutingRule")
            errors = result.get("errors")

            if errors:
                print(f"Error creating muting rule: {errors}")
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



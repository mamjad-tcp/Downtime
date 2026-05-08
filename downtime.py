# import requests
# import json
# import sys

# ENDPOINT = "https://api.newrelic.com/graphql"


# def execute_graphql(api_key, query):
#     headers = {
#         "Content-Type": "application/json",
#         "API-Key": api_key
#     }
#     response = requests.post(
#         ENDPOINT,
#         headers=headers,
#         json={"query": query},
#         timeout=60
#     )
#     response.raise_for_status()
#     return response.json()


# # ---------------- CREATE ----------------
# def create_downtime(api_key, account_id, name, start_time, end_time, monitor_guids):

#     guid_string = ', '.join([f'"{g.strip()}"' for g in monitor_guids if g.strip()])

#     start_time = start_time.replace(' ', 'T')
#     end_time = end_time.replace(' ', 'T')

#     mutation = f"""
#     mutation {{
#       syntheticsCreateOnceMonitorDowntime(
#         accountId: {account_id},
#         name: "{name}",
#         monitorGuids: [{guid_string}],
#         timezone: "America/Chicago",
#         startTime: "{start_time}",
#         endTime: "{end_time}"
#       ) {{
#         guid
#         accountId
#         name
#         monitorGuids
#         timezone
#         startTime
#         endTime
#       }}
#     }}
#     """

#     return execute_graphql(api_key, mutation)


# # ---------------- DESTROY (NOW GUID BASED) ----------------
# def destroy_downtime(api_key, account_id, downtime_guid):

#     print("inside destroy downtime")

#     mutation = f"""
#     mutation {{
#       syntheticsDeleteMonitorDowntime(
#         guid: "{downtime_guid}"
#       ) {{
#         guid
#       }}
#     }}
#     """

#     result = execute_graphql(api_key, mutation)
#     print("Delete result:", json.dumps(result, indent=2))
# # ---------------- MAIN ----------------
# if __name__ == "__main__":

#     api_key = sys.argv[1]
#     account_id = sys.argv[2]
#     operation = sys.argv[3]

#     downtime_name_or_guid = sys.argv[4]

#     if operation == "create":

#         start_time = sys.argv[5]
#         end_time = sys.argv[6]
#         monitor_guids = sys.argv[7].split(",")

#         result = create_downtime(
#             api_key,
#             account_id,
#             downtime_name_or_guid,
#             start_time,
#             end_time,
#             monitor_guids
#         )

#         print("Create response debugging info:")
#         print(json.dumps(result, indent=2))

#         response_data = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime")
#         errors = result.get("errors")

#         if errors:
#             print(f"Error creating downtime: {errors}")

#         if response_data and response_data.get("guid"):
#             downtime_guid = response_data.get("guid")

#             print(
#                 f"Downtime created successfully.\n"
#                 f"GUID: {downtime_guid}\n"
#                 f"Name: {response_data.get('name')}"
#             )

#             print(f"DOWNTIME_GUID={downtime_guid}")

#         else:
#             print("Downtime creation finished, but no GUID returned.")

#     elif operation == "destroy":

#         destroy_downtime(api_key, account_id, downtime_name_or_guid)


import requests
import json
import sys

ACCOUNT_ID = '4473520'
APP_CONDITIONID = '44735169'
ADM_CONDITIONID = '44760251'
AWS_HOST_CONDITIONID = '44735098'
TARGET_GROUP_CONDITIONID = '55638202'
SANDBOX_APP_CONDITIONID = '52535955'
SANDBOX_ADM_CONDITIONID = '52535889'
SANDBOX_SYNTHETIC_CONDITIONID = '4081891'

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

def mute_condition(api_key, account_id, condition_id, mute):

    mutation = f"""
    mutation {{
      alertsUpdateCondition(
        accountId: {account_id},
        conditionId: {condition_id},
        muted: {str(mute).lower()}
      ) {{
        id
        name
        muted
      }}
    }}
    """

    return execute_graphql(api_key, mutation)
def create_downtime(api_key, account_id, name, start_time, end_time, monitor_guids):

    guid_string = ', '.join([f'"{g.strip()}"' for g in monitor_guids if g.strip()])

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

def destroy_downtime(api_key, account_id, downtime_guid):

    print("inside destroy downtime")

    mutation = f"""
    mutation {{
      syntheticsDeleteMonitorDowntime(
        guid:"{downtime_guid}"
      ) {{
        guid
      }}
    }}
    """

    result = execute_graphql(api_key, mutation)
    print("Delete result:", json.dumps(result, indent=2), file=sys.stderr)

if __name__ == "__main__":

    api_key = sys.argv[1]
    account_id = sys.argv[2]
    operation = sys.argv[3]

    downtime_name_or_guid = sys.argv[4]

    if operation == "create":

        start_time = sys.argv[5]
        end_time = sys.argv[6]
        monitor_guids = sys.argv[7].split(",")

        result = create_downtime(
            api_key,
            account_id,
            downtime_name_or_guid,
            start_time,
            end_time,
            monitor_guids
        )

        print("Create response debugging info:", file=sys.stderr)
        print(json.dumps(result, indent=2), file=sys.stderr)

        response_data = result.get("data", {}).get("syntheticsCreateOnceMonitorDowntime")
        errors = result.get("errors")

        if errors:
            print(f"Error creating downtime: {errors}", file=sys.stderr)

        if response_data and response_data.get("guid"):
            downtime_guid = response_data.get("guid")

            print(
                f"Downtime created successfully.\n"
                f"GUID: {downtime_guid}\n"
                f"Name: {response_data.get('name')}",
                file=sys.stderr
            )
            sys.stdout.write(json.dumps({"downtime_guid": downtime_guid}))
            sys.stdout.flush()

        else:
            print("Downtime creation finished, but no GUID returned.", file=sys.stderr)

    elif operation == "destroy":

        destroy_downtime(api_key, account_id, downtime_name_or_guid)
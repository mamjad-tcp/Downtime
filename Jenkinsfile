pipeline{
    agent any 

    environment{
        NEWRELIC_TOKEN = credentials('tcp-newrelic-key')
        TCP_ACCOUNT_ID = '4473520'
        APP_CONDITIONID = '44735169'
        ADM_CONDITIONID = '44760251'
        AWS_HOST_CONDITIONID = '44735098'
        TARGET_GROUP_CONDITIONID = '55638202'
        SANDBOX_APP_CONDITIONID = '52535955'
        SANDBOX_ADM_CONDITIONID = '52535889'
        SANDBOX_SYNTHETIC_CONDITIONID = '4081891'
    }

    parameters {
    string(name: 'BRANCH', defaultValue: 'main', description: 'Branch To Build')
    choice(name: 'CONDITION', choices: ['apply', 'destroy'], description: 'Env for deployment')
    extendedChoice(
        name: 'MUTING_ENVIRONMENT',
        description: 'Select muting environment(s)',
        type: 'PT_CHECKBOX',
        multiSelectDelimiter: ',',
        value: 'Sandbox,App,Admin',
        defaultValue: ''
        )
    string(name: 'START_TIME', defaultValue: '21:00:00', description: 'Set the Start time of Downtime. Add Time in 24 hrs')
    string(name: 'START_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the Start Date of Downtime. YYYY-MM-DD')
    string(name: 'END_TIME', defaultValue: '23:45:00', description: 'Set the End time of Downtime. Add Time in 24 hrs')
    string(name: 'END_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the End Date of Downtime. YYYY-MM-DD')
    extendedChoice(
        name: 'STACKS_NAME',
        description: 'Stacks Name (multi-select)',
        type: 'PT_CHECKBOX',
        multiSelectDelimiter: ',',
        value: '''
            Group-1,
            Group-10,
            Group-10-2,
            Group-12,
            Group-2,
            Group-3,
            Group-4,
            Group-5,
            Group-PHR-1,
            Group-PHR-2,
            Group-PHR-3,
            Group-PHR-4,
            Group-PHR-5,
            Group-PHR-6,
            Group-PHR-7,
            Group-PHR-8,
            Group-PHR-9,
            Group-Prod01,
            Group-Prod03,
            Group-Prod05,
            Group-Prod07,
            Group-Prod09,
            Group-Prod15,
            Group-Prod24,
            Group-Prod25,
            Group-Prod29,
            Group-Prod30,
            Group-Prod33,
            Group-Prod34,
            Group-Prod35,
            Group-Prod36,
            Group-Prod37,
            Group-Prod38,
            Group-Prod39,
            Group-Prod43,
            Group-Prod60,
            Group-Prod61,
            Group-Prod62,
            Group-Prod63,
            Group-Prod64,
            Group-Prod65,
            Group-Prod66,
            Group-Prod67,
            Group-Prod68,
            tcp70alpha,
            Sandbox-Group1,
            Sandbox-Group10,
            Sandbox-Group12,
            Sandbox-Group3,
            Sandbox-Group4,
            Sandbox-Prismhr2,
            Sandbox-Prod05,
            Sandbox-Prod33,
            Sandbox-Prod36,
            Sandbox-Prod37,
            Sandbox-Prod50,
            Sandbox2-Prod37
        '''
    )

    string(name: 'TICKET', defaultValue: 'DEVOPS-12345', description: 'Ticket Number for Backend Configuration/Reference')
    }
stages{
    stage('Build selection payload') {
      steps {
        script {
          // 1) Parse selected environments (Extended Choice returns comma-separated string)
          List<String> selectedEnvs = (params.MUTING_ENVIRONMENT ?: '')
            .split(/\s*,\s*/)
            .collect { it.trim() }
            .findAll { it }

          // 2) Build prod comma-separated string from stacks
          String prodCsv = (params.STACKS_NAME ?: '')
            .split(/\s*,\s*/)
            .collect { it.trim() }
            .findAll { it }
            .join(',')

          // 3) Build condition IDs list based on selected environments
          List<String> conditionIds = []

          if (selectedEnvs.contains('Sandbox')) {
            conditionIds += [
              env.SANDBOX_APP_CONDITIONID,
              env.SANDBOX_ADM_CONDITIONID,
              env.SANDBOX_SYNTHETIC_CONDITIONID
            ]
          }

          if (selectedEnvs.contains('Admin')) {
            conditionIds += [
              env.ADM_CONDITIONID,
              env.AWS_HOST_CONDITIONID,
              env.TARGET_GROUP_CONDITIONID
            ]
          }

          if (selectedEnvs.contains('App')) {
            conditionIds += [
              env.APP_CONDITIONID,
              env.AWS_HOST_CONDITIONID,
              env.TARGET_GROUP_CONDITIONID
            ]
          }

          // Optional: remove duplicates while preserving order
          conditionIds = conditionIds.findAll { it } // remove null/empty
          conditionIds = conditionIds.findAll { it }  // keep non-empty
          def seen = new java.util.LinkedHashSet()
          seen.addAll(conditionIds)
          conditionIds = new java.util.ArrayList(seen)

          env.PROD_CSV = prodCsv
          env.CONDITION_IDS = conditionIds.join(',')
          env.MUTING_ENVIRONMENT_CSV = selectedEnvs.join(',')

          echo "MUTING_ENVIRONMENT: ${selectedEnvs}"
          echo "Stack Name: ${env.PROD_CSV}"
          echo "CONDITION_IDS Selected: ${env.CONDITION_IDS}"
        }
      }
    }

    stage('Apply/Destroy Downtime') {
      steps {
        script {
          if(params.CONDITION == 'apply') {
            echo "Applying downtime for Prods: ${env.PROD_CSV} with conditions: ${env.CONDITION_IDS}"
            withEnv(['API_KEY=' + env.NEWRELIC_TOKEN]) {
              sh '''
                python downtime.py \
                  $API_KEY \
                  $TCP_ACCOUNT_ID \
                  apply \
                  $TICKET \
                  $START_DATE \
                  $START_TIME \
                  $END_DATE \
                  $END_TIME \
                  "$PROD_CSV" \
                  "$MUTING_ENVIRONMENT_CSV"
              '''
            }
          } else if (params.CONDITION == 'destroy') {
            echo "Destroying downtime for prods: ${env.PROD_CSV}"
            withEnv(['API_KEY=' + env.NEWRELIC_TOKEN]) {
              sh '''
                python downtime.py \
                  $API_KEY \
                  $TCP_ACCOUNT_ID \
                  destroy \
                  $TICKET
              '''
            }
          } else {
            error "Invalid CONDITION parameter: ${params.CONDITION}. Must be 'apply' or 'destroy'."
          }
        }
      }
    }
}
}

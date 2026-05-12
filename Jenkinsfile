pipeline{
    agent any 

    environment{
        NEWRELIC_TOKEN = credentials('tcp-newrelic-key')
        TCP_ACCOUNT_ID = '3174604'
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
    groovyScript: '''
        import groovy.json.JsonSlurper

        if (binding.variables.get("CONDITION") == "destroy") {
            return ["N/A"]
        }

        try {
            def url = "https://raw.githubusercontent.com/mamjad-tcp/Downtime/master/stack.json?cb=${System.currentTimeMillis()}"
            def connection = new URL(url).openConnection()
            connection.setUseCaches(false)
            connection.setRequestProperty("Cache-Control", "no-cache, no-store, must-revalidate")
            connection.setRequestProperty("Pragma", "no-cache")
            def jsonText = connection.inputStream.text
            def stacks = new JsonSlurper().parseText(jsonText)
            return stacks.collect { it.group_tag }.sort()
        } catch (Exception e) {
            return ["Error loading stacks: ${e.message}"]
        }
    '''
)

    string(name: 'TICKET', defaultValue: 'DEVOPS-12345', description: 'Ticket Number for Backend Configuration/Reference')
    }
stages{
    // stage('Install Dependencies') {
    //   steps {
    //     sh '''
    //       # Check if Python is installed, if not install it
    //       if ! command -v python3 &> /dev/null; then
    //         echo "Installing Python3..."
    //         apt-get update
    //         apt-get install -y python3 python3-pip
    //       else
    //         echo "Python3 is already installed"
    //         python3 --version
    //       fi
          
    //       # Install required Python packages
    //       echo "Installing Python dependencies..."
    //       pip3 install --upgrade pip
    //       pip3 install requests
    //     '''
    //   }
    // }

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
                python3 --version
            

                '''
              sh '''
                python3 downtime.py \
                  $API_KEY \
                  $TCP_ACCOUNT_ID \
                  apply \
                  $TICKET \
                  $START_DATE \
                  $START_TIME \
                  $END_DATE \
                  $END_TIME \
                  "$PROD_CSV" \
                  "$MUTING_ENVIRONMENT_CSV" \
                  "$CONDITION_IDS"
              '''
            }
          } else if (params.CONDITION == 'destroy') {
            echo "Destroying downtime for prods: ${env.PROD_CSV}"
            withEnv(['API_KEY=' + env.NEWRELIC_TOKEN]) {
              sh '''
                python3 downtime.py \
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

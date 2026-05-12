pipeline {
    agent any

    environment {
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

    stages {
    stages {
        stage('Set Parameters') {
            steps {
                script {
                    properties([
                        parameters([
                            string(name: 'BRANCH', defaultValue: 'main', description: 'Branch To Build'),
                            choice(choices: ['apply', 'destroy'], description: 'Env for deployment', name: 'CONDITION'),
                            [$class: 'ChoiceParameter', choiceType: 'PT_CHECKBOX', filterLength: 1, filterable: false, name: 'MUTING_ENVIRONMENT', randomName: 'choice-parameter-2578984402057198', script: scriptlerScript(isSandboxed: true, scriptlerBuilder: [builderId: '1751381611548_11', parameters: [], propagateParams: false, scriptId: 'newrelic_downtime_environment.groovy'])],
                            string(defaultValue: '21:00:00', name: 'START_TIME', description: 'Set the Start time of Downtime. Add Time in 24 hrs'),
                            string(name: 'START_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the Start Date of Downtime. YYYY-MM-DD'),
                            string(defaultValue: '23:45:00', name: 'END_TIME', description: 'Set the End time of Downtime. Add Time in 24 hrs'),
                            string(name: 'END_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the End Date of Downtime. YYYY-MM-DD'),
                            [$class: 'CascadeChoiceParameter', choiceType: 'PT_CHECKBOX', filterLength: 1, filterable: true, name: 'STACKS_NAME', randomName: 'choice-parameter-stacks-name', referencedParameters: 'CONDITION', script: scriptlerScript(isSandboxed: false, scriptlerBuilder: [builderId: '1751381611548_12', parameters: [], propagateParams: false, scriptId: 'newrelic_downtime_stacks.groovy'])],
                            string(defaultValue: 'DEVOPS-12345', name: 'TICKET', description: 'Ticket Number for Backend Configuration/Reference')
                        ])
                    ])
                }
            }
        }
    }

        stage('Build selection payload') {
            steps {
                script {
                    List<String> selectedEnvs = (params.MUTING_ENVIRONMENT ?: '')
                        .split(/\s*,\s*/)
                        .collect { it.trim() }
                        .findAll { it }

                    String prodCsv = (params.STACKS_NAME ?: '')
                        .split(/\s*,\s*/)
                        .collect { it.trim() }
                        .findAll { it }
                        .join(',')

                    List<String> conditionIds = []

                    if (selectedEnvs.contains('Sandbox')) {
                        conditionIds += [env.SANDBOX_APP_CONDITIONID, env.SANDBOX_ADM_CONDITIONID, env.SANDBOX_SYNTHETIC_CONDITIONID]
                    }
                    if (selectedEnvs.contains('Admin')) {
                        conditionIds += [env.ADM_CONDITIONID, env.AWS_HOST_CONDITIONID, env.TARGET_GROUP_CONDITIONID]
                    }
                    if (selectedEnvs.contains('App')) {
                        conditionIds += [env.APP_CONDITIONID, env.AWS_HOST_CONDITIONID, env.TARGET_GROUP_CONDITIONID]
                    }

                    // Deduplicate preserving order
                    def seen = new java.util.LinkedHashSet(conditionIds.findAll { it })
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
                    if (params.CONDITION == 'apply') {
                        echo "Applying downtime for Prods: ${env.PROD_CSV} with conditions: ${env.CONDITION_IDS}"
                        sh '''
                            python3 downtime.py \
                              $NEWRELIC_TOKEN \
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
                    } else if (params.CONDITION == 'destroy') {
                        echo "Destroying downtime for prods: ${env.PROD_CSV}"
                        sh '''
                            python3 downtime.py \
                              $NEWRELIC_TOKEN \
                              $TCP_ACCOUNT_ID \
                              destroy \
                              $TICKET
                        '''
                    } else {
                        error "Invalid CONDITION: ${params.CONDITION}. Must be 'apply' or 'destroy'."
                    }
                }
            }
        }
    }
}
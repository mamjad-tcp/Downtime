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
        stage('Set Parameters') {
            steps {
                script {
                    properties([
                        parameters([
                            string(name: 'BRANCH', defaultValue: 'main', description: 'Branch To Build'),
                            choice(choices: ['apply', 'destroy'], description: 'Env for deployment', name: 'CONDITION'),
                            [
                                $class: 'DynamicReferenceParameter',
                                choiceType: 'ET_FORMATTED_HTML',
                                name: 'VISIBILITY_CONTROL',
                                randomName: 'choice-parameter-visibility',
                                referencedParameters: 'CONDITION',
                                script: scriptlerScript(isSandboxed: true, scriptlerBuilder: [
                                    builderId: '1751381611548_13',
                                    parameters: [],
                                    propagateParams: false,
                                    scriptId: 'newrelic_downtime_visibility.groovy'
                                ]),
                                omitValueField: true
                            ],
                            [
                                $class: 'ChoiceParameter',
                                choiceType: 'PT_CHECKBOX',
                                filterLength: 1,
                                filterable: false,
                                name: 'MUTING_ENVIRONMENT',
                                randomName: 'choice-parameter-2578984402057198',
                                script: scriptlerScript(isSandboxed: true, scriptlerBuilder: [
                                    builderId: '1751381611548_11',
                                    parameters: [],
                                    propagateParams: false,
                                    scriptId: 'newrelic_downtime_environment.groovy'
                                ])
                            ],
                            string(defaultValue: '21:00:00', name: 'START_TIME', description: 'Set the Start time of Downtime. Add Time in 24 hrs'),
                            string(name: 'START_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the Start Date of Downtime. YYYY-MM-DD ex. 2024-01-01'),
                            string(defaultValue: '23:45:00', name: 'END_TIME', description: 'Set the End time of Downtime. Add Time in 24 hrs'),
                            string(name: 'END_DATE', defaultValue: "${new Date().format('yyyy-MM-dd')}", description: 'Set the End Date of Downtime. YYYY-MM-DD ex. 2024-01-01'),
                            [
                                $class: 'CascadeChoiceParameter',
                                choiceType: 'PT_CHECKBOX',
                                filterLength: 1,
                                filterable: true,
                                name: 'STACK_NAME',
                                randomName: 'choice-parameter-stacks-name',
                                referencedParameters: 'CONDITION',
                                script: scriptlerScript(isSandboxed: false, scriptlerBuilder: [
                                    builderId: '1751381611548_12',
                                    parameters: [],
                                    propagateParams: false,
                                    scriptId: 'newrelic_downtime_stacks.groovy'
                                ])
                            ],
                            string(defaultValue: 'DEVOPS-12345', name: 'TICKET', description: 'Ticket Number for Backend Configuration/Reference')
                        ])
                    ])

                    if (!params.CONDITION) {
                        currentBuild.description = 'First run: parameters registered. Please run again.'
                        error('Parameters were just registered. Please trigger the job again.')
                    }
                }
            }
        }

        stage('Parameters Verification') {
            steps {
                script {
                    currentBuild.displayName = "#${BUILD_ID} - ${params.CONDITION} - ${params.TICKET} - ${params.STACK_NAME}"

                    def profiles = params.MUTING_ENVIRONMENT ? params.MUTING_ENVIRONMENT.tokenize(',') : []
                    def ticket = params.TICKET

                    env.TICKET_SUFFIXED = profiles ? "${ticket}-${profiles.join('-')}" : ticket

                    env.SANDBOX            = profiles.contains('Sandbox') ? 'true' : 'false'
                    env.APPLY_APP_MUTING   = profiles.contains('App')     ? 'true' : 'false'
                    env.APPLY_ADMIN_MUTING = profiles.contains('Admin')   ? 'true' : 'false'

                    if (params.CONDITION == 'apply') {
                        if (params.STACK_NAME && params.STACK_NAME != 'N/A') {
                            echo "Stack List is given"
                            env.STACK_LIST = params.STACK_NAME.replace(',', '-')
                        } else {
                            echo "No stack provided, using default 'Prod00'"
                            env.STACK_LIST = 'Prod00'
                        }
                        if (!params.START_DATE || !params.END_DATE) {
                            error "Please provide the Start/End DATE"
                        }
                        echo "Start/End Date is Provided"
                    } else if (params.CONDITION == 'destroy') {
                        if (params.STACK_NAME && params.STACK_NAME != 'N/A') {
                            echo "Stack List is given"
                            env.STACK_LIST = params.STACK_NAME.replace(',', '-')
                        } else {
                            env.STACK_LIST = 'Prod00'
                        }
                    }

                    echo "MUTING_ENVIRONMENT: ${profiles}"
                    echo "Stack List: ${env.STACK_LIST}"
                    echo "Ticket: ${env.TICKET_SUFFIXED}"
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

                    def seen = new java.util.LinkedHashSet(conditionIds.findAll { it })
                    env.CONDITION_IDS = new java.util.ArrayList(seen).join(',')
                    env.MUTING_ENVIRONMENT_CSV = selectedEnvs.join(',')

                    echo "CONDITION_IDS Selected: ${env.CONDITION_IDS}"
                }
            }
        }

        stage('Apply/Destroy Downtime') {
            steps {
                script {
                    if (params.CONDITION == 'apply') {
                        echo "Applying downtime for Stacks: ${env.STACK_LIST} with conditions: ${env.CONDITION_IDS}"
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
                              "$STACK_LIST" \
                              "$MUTING_ENVIRONMENT_CSV" \
                              "$CONDITION_IDS"
                        '''
                    } else if (params.CONDITION == 'destroy') {
                        echo "Destroying downtime for Stacks: ${env.STACK_LIST}"
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
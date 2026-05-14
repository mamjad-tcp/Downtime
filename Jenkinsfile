pipeline {
    agent any

    environment {
        NEWRELIC_TOKEN = credentials('tcp-newrelic-key')
        TCP_ACCOUNT_ID = '3174604'
        // Condition IDs are now managed inside downtime.py — not here
    }

    stages {

        // ── 1. Register / collect parameters ─────────────────────────────────
        stage('Set Parameters') {
            steps {
                script {
                    properties([
                        parameters([
                            string(
                                name: 'BRANCH',
                                defaultValue: 'main',
                                description: 'Branch to build'
                            ),
                            choice(
                                name: 'CONDITION',
                                choices: ['apply', 'destroy'],
                                description: 'Action: apply or destroy downtime'
                            ),
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
                            string(
                                name: 'START_DATE',
                                defaultValue: "${new Date().format('yyyy-MM-dd')}",
                                description: 'Start date  YYYY-MM-DD'
                            ),
                            string(
                                name: 'START_TIME',
                                defaultValue: '21:00:00',
                                description: 'Start time  HH:MM:SS  (24-hr, America/Chicago)'
                            ),
                            string(
                                name: 'END_DATE',
                                defaultValue: "${new Date().format('yyyy-MM-dd')}",
                                description: 'End date  YYYY-MM-DD'
                            ),
                            string(
                                name: 'END_TIME',
                                defaultValue: '23:45:00',
                                description: 'End time  HH:MM:SS  (24-hr, America/Chicago)'
                            ),
                            [
                                $class: 'CascadeChoiceParameter',
                                choiceType: 'PT_CHECKBOX',
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
                            string(
                                name: 'TICKET',
                                defaultValue: 'DEVOPS-12345',
                                description: 'Ticket number (used as reference prefix in NewRelic names)'
                            )
                        ])
                    ])

                    if (!params.CONDITION) {
                        currentBuild.description = 'First run: parameters registered. Please run again.'
                        error('Parameters were just registered. Please trigger the job again.')
                    }
                }
            }
        }

        // ── 2. Validate & prepare env vars ───────────────────────────────────
        stage('Parameters Verification') {
            steps {
                script {
                    def environments = params.MUTING_ENVIRONMENT
                        ? params.MUTING_ENVIRONMENT.tokenize(',').collect { it.trim() }.findAll { it }
                        : []

                    def stackRaw = (params.STACK_NAME && params.STACK_NAME != 'N/A')
                        ? params.STACK_NAME
                        : 'Prod00'

                    // Comma-separated for python; hyphen-separated for display
                    env.STACK_LIST_CSV    = stackRaw.replace(';', ',')   // normalise any separators
                    env.STACK_LIST_LABEL  = stackRaw.replace(',', '-').replace(';', '-')
                    env.ENVIRONMENTS_CSV  = environments.join(',')
                    env.TICKET            = params.TICKET

                    currentBuild.displayName = (
                        "#${BUILD_ID} | ${params.CONDITION.toUpperCase()} | " +
                        "${params.TICKET} | ${env.STACK_LIST_LABEL}"
                    )

                    if (params.CONDITION == 'apply') {
                        if (!params.START_DATE || !params.END_DATE) {
                            error 'START_DATE and END_DATE are required for apply.'
                        }
                        env.START_DATE = params.START_DATE
                        env.START_TIME = params.START_TIME
                        env.END_DATE   = params.END_DATE
                        env.END_TIME   = params.END_TIME
                    }

                    echo "Action       : ${params.CONDITION}"
                    echo "Ticket       : ${env.TICKET}"
                    echo "Stacks       : ${env.STACK_LIST_CSV}"
                    echo "Environments : ${env.ENVIRONMENTS_CSV}"
                    if (params.CONDITION == 'apply') {
                        echo "Window       : ${env.START_DATE}T${env.START_TIME} → ${env.END_DATE}T${env.END_TIME}"
                    }
                }
            }
        }

        // ── 3. Run downtime.py ────────────────────────────────────────────────
        stage('Apply / Destroy Downtime') {
            steps {
                script {
                    if (params.CONDITION == 'apply') {
                        sh '''
                            python3 downtime.py \
                              "$NEWRELIC_TOKEN"   \
                              "$TCP_ACCOUNT_ID"   \
                              apply               \
                              "$TICKET"           \
                              "$START_DATE"       \
                              "$START_TIME"       \
                              "$END_DATE"         \
                              "$END_TIME"         \
                              "$STACK_LIST_CSV"   \
                              "$ENVIRONMENTS_CSV"
                        '''
                    } else if (params.CONDITION == 'destroy') {
                        sh '''
                            python3 downtime.py \
                              "$NEWRELIC_TOKEN" \
                              "$TCP_ACCOUNT_ID" \
                              destroy           \
                              "$TICKET"
                        '''
                    } else {
                        error "Invalid CONDITION: '${params.CONDITION}'. Must be 'apply' or 'destroy'."
                    }
                }
            }
        }
    }
}
// Groovy Scriptler Script for Jenkins
// This script loads stack names from the stack.json file for use in Jenkins parameter choices

import groovy.json.JsonSlurper

// Get the CONDITION parameter from Jenkins (if available in the context)
// Note: Adjust 'CONDITION' based on your actual parameter name
def condition = binding?.variables?.get('CONDITION') ?: params?.CONDITION ?: 'apply'

// If destroying, don't need to load stacks
if (condition == "destroy") {
    return ["N/A"]
}

try {
    // URL to the stack.json file from your repository
    def url = "https://raw.githubusercontent.com/tcp-software/newrelic-terraform/main/terraform/timeclockPlus/stack.json"
    
    // Fetch and parse the JSON
    def jsonText = new URL(url).text
    def stacks = new JsonSlurper().parseText(jsonText)
    
    // Extract group_tag values and sort alphabetically
    def stackNames = stacks.collect { it.group_tag }.sort()
    
    println("Successfully loaded ${stackNames.size()} stacks from repository")
    return stackNames
    
} catch (Exception e) {
    println("Error loading stacks: ${e.message}")
    e.printStackTrace()
    return ["Error loading stacks: ${e.message}"]
}

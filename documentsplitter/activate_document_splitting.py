#!/usr/bin/env python3
import boto3
import sys
import argparse
import json


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Update Bedrock Data Automation project configuration')
    parser.add_argument('project_name', help='Name of the project to update')
    args = parser.parse_args()

    # Initialize Bedrock client
    client = boto3.client('bedrock-data-automation')

    print(f"Get project list and find matching project for {args.project_name}")
    # Get project list and find matching project
    projects = client.list_data_automation_projects()["projects"]
    project_arn = next((p["projectArn"] for p in projects if p["projectName"] == args.project_name), None)

    if not project_arn:
        print(f"No data project named '{args.project_name}' found, please create it first.")
        sys.exit(1)

    # Get project details
    project = client.get_data_automation_project(projectArn=project_arn)["project"]
    # Get project blueprints
    blueprints = client.list_blueprints(projectFilter={'projectArn': project["projectArn"]})["blueprints"]

    print(f"Activating document splitting for project: {args.project_name}, {project_arn}")
    # Update project configuration
    update_response = client.update_data_automation_project(
        projectArn=project_arn,
        standardOutputConfiguration=project["standardOutputConfiguration"],
        customOutputConfiguration={"blueprints": blueprints},
        overrideConfiguration={'document': {'splitter': {'state': 'ENABLED'}}}
    )

    # Get updated project configuration
    updated_project = client.get_data_automation_project(projectArn=project_arn)["project"]

    print("\nUpdated override configuration of project:")
    print(json.dumps(updated_project.get('overrideConfiguration', {}), indent=2))


if __name__ == "__main__":
    main()
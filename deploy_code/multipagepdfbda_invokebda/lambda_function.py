# /*
#  * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  * SPDX-License-Identifier: MIT-0
#  *
#  * Permission is hereby granted, free of charge, to any person obtaining a copy of this
#  * software and associated documentation files (the "Software"), to deal in the Software
#  * without restriction, including without limitation the rights to use, copy, modify,
#  * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
#  * permit persons to whom the Software is furnished to do so.
#  *
#  * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
#  * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
#  * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
#  * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
#  * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#  * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#  */


import json
import boto3
import os
import time

def lambda_handler(event, context):
    print(event)
    # Configuration
    AWS_REGION = os.environ.get('REGION')
    BUCKET_NAME = event.get('bucket')
    OUTPUT_PATH = os.environ.get('OUTPUT_PATH', 'BDA/Output')
    PROJECT_ID = os.environ.get('PROJECT_ID')
    
    # Get file key from event
    key = event.get('key')
    file_name = key.split('/')[-1]
    
    # AWS SDK clients
    bda = boto3.client('bedrock-data-automation-runtime', region_name=AWS_REGION)
    sts = boto3.client('sts')
    
    # Get AWS account ID
    aws_account_id = sts.get_caller_identity().get('Account')
    
    # Set up S3 URIs
    input_s3_uri = f"s3://{BUCKET_NAME}/{key}"  # Full path to the file
    print(input_s3_uri)
    print(BUCKET_NAME)
    output_s3_uri = f"s3://{BUCKET_NAME}/{OUTPUT_PATH}"  # Output folder
    data_automation_arn = f"arn:aws:bedrock:{AWS_REGION}:{aws_account_id}:data-automation-project/{PROJECT_ID}"
    
    print(f"Invoking Bedrock Data Automation for '{file_name}'")
    
    # Invoke BDA
    response = invoke_data_automation(input_s3_uri, output_s3_uri, data_automation_arn, aws_account_id, bda,AWS_REGION)
    invocation_arn = response['invocationArn']
    
    # Wait for completion
    data_automation_status = wait_for_data_automation_to_complete(invocation_arn, bda)
    
    if data_automation_status['status'] == 'Success':
        job_metadata_s3_uri = data_automation_status['outputConfiguration']['s3Uri']
        
        # Return the results
        return {
            'status': 'success',
            'job_metadata_uri': job_metadata_s3_uri,
            #'original_event': event
        }
    else:
        return {
            'status': 'failed',
            'error': data_automation_status.get('error', 'Unknown error'),
            #'original_event': event
        }    
    # Continuing the invoke_bda Lambda function
def invoke_data_automation(input_s3_uri, output_s3_uri, data_automation_arn, aws_account_id, bda_client, aws_region):
    params = {
        'inputConfiguration': {
            's3Uri': input_s3_uri
        },
        'outputConfiguration': {
            's3Uri': output_s3_uri
        },
        'dataAutomationConfiguration': {
            'dataAutomationProjectArn': data_automation_arn
        },
        'dataAutomationProfileArn': f"arn:aws:bedrock:{aws_region}:{aws_account_id}:data-automation-profile/us.data-automation-v1"
    }

    response = bda_client.invoke_data_automation_async(**params)
    return response

def wait_for_data_automation_to_complete(invocation_arn, bda_client, loop_time_in_seconds=2):
    while True:
        response = bda_client.get_data_automation_status(
            invocationArn=invocation_arn
        )
        status = response['status']
        if status not in ['Created', 'InProgress']:
            print(f"BDA processing completed with status: {status}")
            return response
        print(".", end='', flush=True)
        time.sleep(loop_time_in_seconds)
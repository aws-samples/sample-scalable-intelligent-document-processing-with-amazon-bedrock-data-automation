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

import copy
import json
import boto3
import botocore
import os
import io
import datetime
import tempfile
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

s3_client = boto3.client('s3')
sagemaker_a2i_runtime = boto3.client('sagemaker-a2i-runtime')

def start_human_loop(human_loop_name, flow_definition_arn, input_content):
    """
    Start a human loop in Amazon SageMaker Ground Truth.
    Parameters:
    human_loop_name (str): The name of the human loop.
    flow_definition_arn (str): The ARN of the flow definition.
    input_content (str): The input content for the human loop as a JSON string.
    Returns:
    dict: Response from the start_human_loop API call.
    """
    # Start the human loop
    response = sagemaker_a2i_runtime.start_human_loop(
        HumanLoopName=human_loop_name,
        FlowDefinitionArn=flow_definition_arn,
        HumanLoopInput={
            'InputContent': json.dumps(input_content)
        }
    )
    return response

def write_ai_response_to_bucket(bucket, s3location, data):
    client = boto3.client('s3')
    response = client.put_object(
        Body = json.dumps(data),
        Bucket = bucket,
        Key = s3location + "/ai/output.json"
    )
    return response

def dump_task_token_in_dynamodb(event, total_pages=1):
    """
    Store task token and document metadata in DynamoDB
    
    Parameters:
    event (dict): The event containing human_loop_id, process_key, and token
    total_pages (int): Total number of pages in the document
    """
    dynamodb = boto3.client('dynamodb')
    
    # Check if an entry already exists for this document
    try:
        response = dynamodb.get_item(
            TableName=os.environ['ddb_tablename'],
            Key={'jobid': {'S': event["human_loop_id"]}}
        )
        
        # If entry exists, we don't need to create it again
        if 'Item' in response:
            print(f"Entry already exists for job {event['human_loop_id']}")
            return response
    except Exception as e:
        print(f"Error checking for existing entry: {str(e)}")
    
    # Create new entry with page tracking information
    response = dynamodb.put_item(
        TableName=os.environ['ddb_tablename'],
        Item={
            'jobid': {'S': event["human_loop_id"]},
            'imagepath': {'S': event["process_key"]},
            'callback_token': {'S': event["token"]},
            'extension': {'S': event["extension"]},
            'total_pages': {'N': str(total_pages)},
            'completed_pages': {'N': '0'},
            'document_id': {'S': event["id"]},
            'is_complete': {'BOOL': False}
        }
    )
    return response

def filter_labels_by_page(a2iinput):
    """
    Filter labels in a2iinput to only include those from the page specified in the taskObject filename.
    
    Args:
        a2iinput (dict): The a2iinput dictionary containing taskObject and labels
        
    Returns:
        dict: Updated a2iinput with filtered labels
    """
    # Extract page number from the taskObject filename
    task_object_path = a2iinput.get('taskObject', '')
    
    # Extract the filename from the S3 URI
    filename = task_object_path.split('/')[-1]
    
    # Extract the page number from the filename (removing .png extension)
    try:
        page_number = int(filename.split('.')[0])
    except (ValueError, IndexError):
        # If we can't extract a valid page number, return the original input
        return a2iinput
    
    # Filter labels to only include those with matching page number
    filtered_labels = []
    for label in a2iinput.get('labels', []):
        # Include labels that have a matching page number or labels without page info
        if 'page' in label and label['page'] == page_number:
            filtered_labels.append(label)
        elif 'page' not in label or label['page'] is None:
            # For labels without page information, we can either:
            # 1. Include them (as done here)
            # 2. Exclude them (remove this condition)
            # 3. Only include them for page 0 (add condition: if page_number == 0)
            filtered_labels.append(label)
    
    # Update the a2iinput with filtered labels
    result = a2iinput.copy()
    result['labels'] = filtered_labels
    
    return result

def lambda_handler(event, context):
    print(event)
    for record in event["Records"]:
        body = json.loads(record["body"])
        
        # Extract the file extension from the input key
        input_extension = os.path.splitext(body["key"])[1].lower()
        
        # Convert wip_key to string if it's an integer
        if isinstance(body["wip_key"], int):
            print("converting to string")
            body["wip_key"] = str(body["wip_key"])
        
        # Use .png for PDFs, otherwise use the original extension
        output_extension = '.png' if input_extension.lower() == '.pdf' else input_extension
        
        # Determine total number of pages
        total_pages = 1  # Default to 1 page
        if "image_keys" in body and isinstance(body["image_keys"], list):
            total_pages = len(body["image_keys"])
            print(f"Document has {total_pages} pages")
        
        # Store document-level metadata in DynamoDB
        # We'll use the document ID as a base for tracking all pages
        document_base_id = body['id']
        
        # Check if we have image_keys array to process multiple pages
        if "image_keys" in body and isinstance(body["image_keys"], list) and len(body["image_keys"]) > 0:
            # Process each page in the image_keys array
            for page_index in body["image_keys"]:
                process_page(body, page_index, output_extension, total_pages, document_base_id)
        else:
            # Process just the current page from wip_key
            current_page_index = int(body["wip_key"]) if body["wip_key"].isdigit() else 0
            process_page(body, current_page_index, output_extension, total_pages, document_base_id)
        
        # Delete the SQS message
        client = boto3.client('sqs')
        response = client.delete_message(
            QueueUrl=os.environ['sqs_url'],
            ReceiptHandle=record["receiptHandle"]
        )
    
    return "all_done_check"

def process_page(body, page_index, output_extension, total_pages, document_base_id):
    """Process a single page and start human loop if needed"""
    # Set up page-specific fields
    page_body = body.copy()
    page_body["process_key"] = f"wip/{body['id']}/{page_index}{output_extension}"
    page_body["human_loop_id"] = f"{body['id']}i{page_index}"
    page_body["s3_location"] = f"{page_body['process_key']}/ai/output.json"
    page_body["extension"] = output_extension
    
    # For PDFs, we need to point to the specific page PNG
    if output_extension == '.png':
        # Use the PNG file for this specific page
        page_body["input_s3_uri"] = f"s3://{body['bucket']}/wip/{body['id']}/{page_index}{output_extension}"
    else:
        # For other formats, use the original document but specify the page
        targetkey = body["key"].replace("uploads", "uploads-output")
        page_body["input_s3_uri"] = f"s3://{body['bucket']}/wip/{body['id']}/{page_index}{output_extension}"
        #page_body["input_s3_uri"] = f"s3://{body['bucket']}/{body['key']}#page={page_index+1}"
        page_body["output_s3_uri"] = f"s3://{body['bucket']}/{targetkey}"
    
    print(f"Processing page {page_index}, input URI: {page_body['input_s3_uri']}")
    
    # Process this page
    if "a2iinput" in page_body and page_body["a2iinput"] != "none":
        # Create a deep copy of a2iinput to avoid modifying the original
        import copy
        a2i_input = copy.deepcopy(page_body["a2iinput"])
        
        # Update the taskObject to point to the specific page
        a2i_input["taskObject"] = page_body["input_s3_uri"]
        
        # Filter labels to only include those for this specific page
        filtered_labels = []
        for label in a2i_input.get("labels", []):
            if "page" in label and label["page"] == page_index:
                # Create a copy of the label with page set to 0 for A2I display
                label_copy = label.copy()
                label_copy["page"] = 0  # A2I expects page 0 for display
                filtered_labels.append(label_copy)
        
        # Update the a2i input with filtered labels
        a2i_input["labels"] = filtered_labels
        
        print(f"Page {page_index} has {len(filtered_labels)} labels")
        
        # Add document metadata to page_body
        page_body["id"] = document_base_id
        page_body["total_pages"] = total_pages
        
        # Process with a2iinput
        write_ai_response_to_bucket(page_body['bucket'], page_body["process_key"], page_body["inference_result"])
        
        # Store task token and page metadata in DynamoDB
        dump_task_token_in_dynamodb(page_body, total_pages)
        
        # Start human loop
        response = start_human_loop(page_body["human_loop_id"], os.environ['human_workflow_arn'], a2i_input)
    else:
        # If a2iinput is not available, check for inference_result
        if "inference_result" in page_body:
            # Just write the inference result to S3 and return to Step Function
            write_ai_response_to_bucket(page_body['bucket'], page_body["process_key"], page_body["inference_result"])
            
            # Get token directly from the event and return to Step Function
            if "token" in page_body:
                try:
                    response = invoke_to_get_back_to_stepfunction(page_body["token"], page_body)
                except Exception as e:
                    print(f"Error returning to Step Function: {str(e)}")
            else:
                print("No token found in the message body")
        else:
            print("Neither a2iinput nor inference_result found in the message body")

def invoke_to_get_back_to_stepfunction(token, body):
    client = boto3.client('stepfunctions')
    response = client.send_task_success(
        taskToken=token,
        output=json.dumps(body)
    )
    return response
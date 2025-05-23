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
from boto3.dynamodb.conditions import Key
import decimal

# Helper class to convert Decimal to int/float for JSON serialization
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return int(o) if o % 1 == 0 else float(o)
        return super(DecimalEncoder, self).default(o)


def return_to_stepfunctions(payload):
    client = boto3.client('stepfunctions')
    
    # If payload contains a list of tokens, process each one
    tokens = payload['tokens'] if isinstance(payload['tokens'], list) else [payload['tokens']]
    responses = []
    
    for token in tokens:
        response = client.send_task_success(
            taskToken = token,
            output = json.dumps({ 
                "includes_human": "yes",
                "output_dest": payload["final_dest"],
                "bucket": payload["bucket"],
                "id": payload["id"],
                "key": payload["key"]
            })
        )
        responses.append(response)
    
    return responses    

def write_to_s3_human_response(payload):
    client = boto3.client('s3')
    print(payload["final_dest"])
    print(payload["kv_list"])
    print(payload["bucket"])
    response = client.put_object(
        Body = json.dumps(payload["kv_list"]),
        Bucket = payload["bucket"],
        Key = payload["final_dest"]
    )
    return response

def create_human_kv_list(payload):
    data = payload["response"]["humanAnswers"][0]["answerContent"]
    print(data)
    return data
    
def get_s3_data(payload):
    s3 = boto3.resource('s3')
    obj = s3.Object(payload["bucket"], payload["key"])
    body = obj.get()['Body'].read()
    return json.loads(body)



def get_token_and_check_completion(payload):
    """
    Get the task tokens and check if all pages of the document have been reviewed.
    Only returns the tokens if all pages are complete.
    Uses begins_with on the document ID prefix to find all pages.
    Returns a list of unique tokens instead of a single token.
    """
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['ddb_tablename'])
    
    # Extract the document ID prefix (remove the last 2 characters which should be 'iX')
    # The human_loop_id format is typically {document_id}i{page_number}
    document_id_prefix = payload["human_loop_id"][:-2]  # Remove the last 2 chars (e.g., 'i0', 'i1')
    
    print(f"Processing completion for document prefix {document_id_prefix}, current page {payload['human_loop_id']}")
    
    # Mark this page as complete by updating the existing record
    try:
        # First get the current record to extract its callback_token (sort key)
        current_page_response = table.query(KeyConditionExpression=Key('jobid').eq(payload["human_loop_id"]))
        
        if not current_page_response['Items']:
            print(f"No record found for job ID {payload['human_loop_id']}")
            return None, None
            
        current_item = current_page_response['Items'][0]
        callback_token = current_item['callback_token']
        
        # Update the existing record with the correct primary key
        table.update_item(
            Key={
                'jobid': payload["human_loop_id"],
                'callback_token': callback_token
            },
            UpdateExpression="set is_complete = :i",
            ExpressionAttributeValues={
                ':i': True
            }
        )
        print(f"Marked page {payload['human_loop_id']} as complete in DynamoDB")
    except Exception as e:
        print(f"Error marking page as complete: {str(e)}")
    
    # Find all pages for this document using begins_with on the document ID prefix
    try:
        # Query the GSI for all items with this document_id
        all_pages_response = table.query(
            IndexName='document_id-index',
            KeyConditionExpression=Key('document_id').eq(document_id_prefix)
        )
        
        print(f"Found {len(all_pages_response['Items'])} pages for document prefix {document_id_prefix}")
        
        # Check if all pages are complete
        all_pages_complete = True
        extension = None
        
        # First check if all pages are complete
        for page_item in all_pages_response['Items']:
            page_id = page_item['jobid']
            is_complete = page_item.get('is_complete', False)
            
            # Capture extension from any page (should be the same for all pages of this document)
            if extension is None:
                extension = page_item.get('extension', '')
                
            print(f"Page {page_id}: is_complete = {is_complete}")
            
            if not is_complete:
                all_pages_complete = False
                print(f"Page {page_id} is not yet complete")
                break
        
        if all_pages_complete:
            # If all pages are complete, collect all unique tokens
            # Use a set to automatically remove duplicates
            unique_tokens = set()
            for page_item in all_pages_response['Items']:
                token = page_item.get('callback_token')
                if token:
                    unique_tokens.add(token)
            
            # Convert set back to list
            tokens = list(unique_tokens)
            
            print(f"All {len(all_pages_response['Items'])} pages for document prefix {document_id_prefix} are complete.")
            print(f"Collected {len(tokens)} unique tokens from {len(all_pages_response['Items'])} pages.")
            return tokens, extension
        else:
            print(f"Not all pages for document prefix {document_id_prefix} are complete yet. Waiting for remaining pages.")
            return None, None
            
    except Exception as e:
        print(f"Error checking page completion: {str(e)}")
        return None, None

def create_final_dest(id, key,extension):
    prefix = key[:3].lower()
    if prefix != "wip":
        final_dest = "wip/" + id + "/0"  + extension 
    else:
        final_dest = key
    return final_dest + "/human/output.json"

def create_payload(event):
    payload = {}
    detail = event["detail"]
    cur = detail["humanLoopOutput"]["outputS3Uri"]
    
    cur = cur.replace("s3://", "")
    payload["bucket"] = cur[:cur.find("/")]
    payload["key"] = cur[len(payload["bucket"])+1:]

    payload["response"] = get_s3_data(payload)
    
    cur1 = payload["response"]["inputContent"]["taskObject"]
    cur1 = cur1.replace("s3://", "")
    payload["bucket1"] = cur1[:cur1.find("/")]
    payload["key1"] = cur1[len(payload["bucket1"])+1:]
    
    payload["human_loop_id"] = payload["response"]["humanLoopName"]
    payload["id"] = payload["human_loop_id"][:payload["human_loop_id"].rfind("i")]

    
    # Get tokens only if all pages are complete
    tokens, extension = get_token_and_check_completion(payload)
    payload["tokens"] = tokens  # Now storing a list of tokens instead of single token
    payload["extension"] = extension

    payload["final_dest"] = create_final_dest(payload["id"], payload["key1"], extension)
    
    return payload

def lambda_handler(event, context):
    print(event)
    if event["detail"]["humanLoopStatus"] == "Completed":
        payload = create_payload(event)
        payload["kv_list"] = create_human_kv_list(payload)
        
        # Always write the human review results to S3
        response = write_to_s3_human_response(payload)
        
        # Only return to Step Functions if all pages are complete (tokens is not None)
        if payload.get("tokens") != None:
            print("all pages complete")
            print(f"Processing {len(payload['tokens'])} tokens")
            response = return_to_stepfunctions(payload)
            return "all done - all pages complete"
        else:
            return "page processed - waiting for remaining pages"
    else:
        return "dont_care"
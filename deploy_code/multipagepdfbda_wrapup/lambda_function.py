import json
import boto3
import botocore
import os
import copy
from boto3.dynamodb.conditions import Key
from gather_data import gather_and_combine_data

def lambda_handler(event, context):
    print(event)
    # Gather all of the data into a CSV
    data, s3outputpath, payload, processed_keys = gather_and_combine_data(event)
    
    print(f"s3outputpath {s3outputpath}")
    
    try:
        # Check if s3outputpath contains the necessary information
        if isinstance(s3outputpath, dict) and 'original_responses_key' in s3outputpath and 'a2i_responses_key' in s3outputpath:
            bucket = s3outputpath['bucket']
            
            # Get original responses from S3
            s3_client = boto3.client('s3')
            original_response = s3_client.get_object(
                Bucket=bucket,
                Key=s3outputpath['original_responses_key']
            )
            original_response_body = original_response["Body"].read().decode('utf-8')
            print(f"Original response body: {original_response_body}")
            original_responses = json.loads(original_response_body)
            
            # Get A2I responses from S3
            a2i_response = s3_client.get_object(
                Bucket=bucket,
                Key=s3outputpath['a2i_responses_key']
            )
            a2i_response_body = a2i_response["Body"].read().decode('utf-8')
            print(f"A2I response body: {a2i_response_body}")
            a2i_responses = json.loads(a2i_response_body)
            
            # Find the first AI page to use as a template
            ai_template_key = None
            for key in original_responses:
                if key.endswith('_ai'):
                    ai_template_key = key
                    break
            
            if not ai_template_key:
                print("No AI template found in original responses")
                return s3outputpath
                
            # Get the template structure
            ai_template = original_responses[ai_template_key]

            # Write BDA responses to S3 (renamed from original_responses)
            bda_responses_key = s3outputpath['original_responses_key'].replace('-original-responses.json', '-bda-responses.json')
            s3_client.put_object(
                Body=json.dumps({"bda_responses": ai_template}, indent=2),
                Bucket=bucket,
                Key=bda_responses_key,
                ContentType='application/json'
            ) 

            if payload["a2iinput"] != "none":
                # Create a single combined restructured response
                combined_restructured = copy.deepcopy(ai_template)
            
                # Track which pages have been processed
                processed_pages = []
            
                # Process each page in A2I responses and combine updates
                for page_key, page_data in a2i_responses.items():
                    if not page_key.endswith('_human'):
                        continue
                    
                    processed_pages.append(page_key)
                    print(f"Processing A2I page: {page_key}")
                    
                    # Update the combined structure with values from this page
                    update_with_flattened_values(combined_restructured, page_data)
                
                # Create the final restructured response
                restructured_responses = {
                    "human_responses": combined_restructured,
                    "processed_pages": processed_pages
                }
            
                print(f"Final restructured responses: {json.dumps(restructured_responses, indent=2)}")

                # Write human responses to S3 (renamed from restructured-a2i-responses)
                human_responses_key = s3outputpath['a2i_responses_key'].replace('-a2i-responses.json', '-human-responses.json')
                s3_client.put_object(
                    Body=json.dumps(restructured_responses, indent=2),
                    Bucket=bucket,
                    Key=human_responses_key,
                    ContentType='application/json'
                )

            # Delete the original files that we don't need anymore
            try:
                print(f"Deleting original responses file: {s3outputpath['original_responses_key']}")
                s3_client.delete_object(
                    Bucket=bucket,
                    Key=s3outputpath['original_responses_key']
                )
                
                print(f"Deleting A2I responses file: {s3outputpath['a2i_responses_key']}")
                s3_client.delete_object(
                    Bucket=bucket,
                    Key=s3outputpath['a2i_responses_key']
                )
                
                print("Successfully deleted original and A2I response files")
            except Exception as delete_error:
                print(f"Warning: Error deleting files: {str(delete_error)}")
                
            
            # Update the response to include the new keys
            s3outputpath['bda_responses_key'] = bda_responses_key
            s3outputpath['human_responses_key'] = human_responses_key
            
            # Remove the old keys that we don't need anymore
            if 'original_responses_key' in s3outputpath:
                del s3outputpath['original_responses_key']
            if 'a2i_responses_key' in s3outputpath:
                del s3outputpath['a2i_responses_key']
            if 'restructured_a2i_responses_key' in s3outputpath:
                del s3outputpath['restructured_a2i_responses_key']
    except Exception as e:
        print(f"Error restructuring responses: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return s3outputpath

def update_with_flattened_values(structure, flattened_values):
    """
    Updates the structure with values from the flattened key-value pairs.
    
    Args:
        structure: The nested structure to update (modified in place)
        flattened_values: Dict with flattened keys like "PARENT/CHILD" or "PARENT.CHILD"
    """
    print(f"Updating structure with flattened values: {json.dumps(flattened_values, indent=2)}")
    
    # Process direct keys first (no separators)
    for key, value in flattened_values.items():
        if '/' not in key and '.' not in key:
            if key in structure:
                print(f"Updating direct key: {key} = {value}")
                structure[key] = value
            else:
                print(f"Creating new direct key: {key} = {value}")
                structure[key] = value
    
    # Process nested keys
    for key, value in flattened_values.items():
        # Handle both slash and dot separators
        if '/' in key or '.' in key:
            # Split by either slash or dot
            parts = key.split('/') if '/' in key else key.split('.')
            current = structure
            path_so_far = []
            
            # Navigate to the nested location
            for i, part in enumerate(parts):
                path_so_far.append(part)
                
                if i == len(parts) - 1:
                    # Last part - update the value
                    print(f"Setting value at {'.'.join(path_so_far)} = {value}")
                    current[part] = value
                else:
                    # Navigate deeper, creating structure as needed
                    if part not in current:
                        print(f"Creating missing structure for: {'.'.join(path_so_far)}")
                        current[part] = {}
                    elif not isinstance(current[part], dict):
                        print(f"Converting to dict at {'.'.join(path_so_far)}")
                        # Convert to dict if it's not already
                        current[part] = {}
                    current = current[part]
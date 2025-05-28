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
import botocore
import os
from operator import itemgetter


def does_exsist(bucket, key):
    s3 = boto3.resource('s3')
    try:
        s3.Object(bucket, key).load()
    except botocore.exceptions.ClientError as e:
        return False
    else:
        return True

def write_data_to_bucket(payload, name, csv):
    dest = "wip/" + payload["id"] + "/csv/" + name.replace(".png", ".csv")
    s3 = boto3.resource('s3')
    s3.Object(payload["bucket"], dest).put(Body=csv)
    return dest

def get_data_from_bucket(bucket, key):
    print(bucket)
    print(key)
    client = boto3.client('s3')
    response = client.get_object(
        Bucket=bucket,
        Key=key
    )
    data = json.load(response["Body"])
    
    return data

def create_csv(kv_list, give_type, page_number=None):
    if isinstance(kv_list, str):
        try:
            kv_dict = json.loads(kv_list)
        except json.JSONDecodeError:
            return "Error: Invalid JSON string", ""
    elif isinstance(kv_list, dict):
        kv_dict = kv_list
    else:
        return "Error: Invalid input type", ""
    
    outputkey = ""
    outputvalue = ""

    def process_dict(dictionary, prefix=""):
        nonlocal outputkey, outputvalue
        for key, value in dictionary.items():
            if isinstance(value, dict):
                # Recursively process nested dictionaries
                process_dict(value, f"{key}_")
            else:
                # If there's a prefix, use it; otherwise, use just the key
                final_key = (prefix + key if prefix else key).replace(",", "")
                
                # Add page number to the key if provided
                if page_number is not None:
                    keytype = f"page{page_number}_{final_key}-{give_type}"
                else:
                    keytype = f"{final_key}-{give_type}"
                
                outputkey += keytype + ","
                outputvalue += str(value).replace(",", "") + ","

    process_dict(kv_dict)
    
    # Remove trailing commas
    outputkey = outputkey.rstrip(',')
    outputvalue = outputvalue.rstrip(',')
    
    return outputkey, outputvalue

def write_to_s3(csv, payload, original_uplolad_key, image_keys):
    client = boto3.client('s3')
    
    # Extract a meaningful name from the original upload key
    if "/" in original_uplolad_key:
        filename = original_uplolad_key.split("/")[-1].split(".")[0]
    else:
        filename = original_uplolad_key.split(".")[0]
    
    # Format image_keys for the filename
    if image_keys and isinstance(image_keys, list):
        # Convert all items to strings and join with hyphens
        image_keys_str = "-".join([str(k) for k in image_keys])
    else:
        image_keys_str = "unknown"
    
    # Create a single output file for all pages with image_keys in the name
    output_key = f"complete/{payload['id']}-{filename}-pages-{image_keys_str}-output.csv"
    
    response = client.put_object(
        Body = csv,
        Bucket = payload["bucket"],
        Key = output_key
    )
    return payload["bucket"], output_key

def write_json_to_s3(data, bucket, key):
    """Write JSON data to S3 bucket"""
    client = boto3.client('s3')
    response = client.put_object(
        Body=json.dumps(data, indent=2),
        Bucket=bucket,
        Key=key,
        ContentType='application/json'
    )
    return response

def reconstruct_original_format(a2i_response, structure_map):
    """
    Reconstructs the original format from the A2I response using the structure map.
    
    Args:
        a2i_response: The response from A2I with updated field values
        structure_map: The structure map from the flattening process
    
    Returns:
        The reconstructed data in the original format
    """
    result = [{} for _ in range(max(item['section_idx'] for item in structure_map.values()) + 1)]
    
    # First, create the structure
    for field_name, structure_info in structure_map.items():
        section_idx = structure_info['section_idx']
        
        if '.' not in field_name and '[' not in field_name:  # Root level field
            if structure_info['type'] == 'array':
                result[section_idx][field_name] = [{} for _ in range(structure_info['length'])]
            elif structure_info['type'] == 'object':
                result[section_idx][field_name] = {}
            elif structure_info['type'] == 'simple':
                # Will be filled in later with values
                pass
    
    # Now fill in the values from A2I response
    for field in a2i_response:
        components = field['path_components']
        value = field['value']
        
        if 'array_index' in components:
            # This is a field in an array item
            root = components['root']
            index = components['array_index']
            field_name = components['field']
            
            # Create the confidence structure
            field_data = {
                'value': value,
                'confidence': field['confidence']
            }
            if field['geometry']:
                field_data['geometry'] = field['geometry']
                
            result[structure_map[root]['section_idx']][root][index][field_name] = field_data
        elif 'field' in components:
            # This is a field in an object
            root = components['root']
            field_name = components['field']
            
            # Create the confidence structure
            field_data = {
                'value': value,
                'confidence': field['confidence']
            }
            if field['geometry']:
                field_data['geometry'] = field['geometry']
                
            result[structure_map[root]['section_idx']][root][field_name] = field_data
        else:
            # This is a simple field at root level
            root = components['root']
            
            # Create the confidence structure
            field_data = {
                'value': value,
                'confidence': field['confidence']
            }
            if field['geometry']:
                field_data['geometry'] = field['geometry']
                
            result[structure_map[root]['section_idx']][root] = field_data
    
    return result

def curate_data(base_image_keys, payload, image_keys):
    # Initialize data structures to collect all AI and human data
    all_ai_keys = []
    all_ai_values = []
    all_human_keys = []
    all_human_values = []
    
    # Track which files were processed
    processed_files = []
    
    # Store original and reconstructed data
    original_responses = {}
    a2i_responses = {}
    
    # For AI data, we only need to process it once since it's duplicated across pages
    # Get the first available AI data
    ai_data = None
    ai_page_number = None
    
    for i, base_key in enumerate(base_image_keys):
        page_number = base_key[base_key.rfind("/") + 1:]
        page_number = int(page_number[:page_number.find(".")])
        
        # Get AI data (only for the first page we find it)
        if ai_data is None:
            ai_key = base_key + "/ai/output.json"
            if does_exsist(payload["bucket"], ai_key):
                ai_data = get_data_from_bucket(payload["bucket"], ai_key)
                ai_page_number = page_number
                print(f"AI data found on page {page_number}:", ai_data)
                
                # Store original AI response (only once)
                original_responses[f"page_{page_number}_ai"] = ai_data
                
                datakey, datavalue = create_csv(ai_data, "ai", page_number)
                all_ai_keys.append(datakey)
                all_ai_values.append(datavalue)
                processed_files.append(ai_key)
    
    # Now process human data for all pages
    for i, base_key in enumerate(base_image_keys):
        page_number = base_key[base_key.rfind("/") + 1:]
        page_number = int(page_number[:page_number.find(".")])
        
        # Get human data
        human_key = base_key + "/human/output.json"
        if does_exsist(payload["bucket"], human_key):
            temp_data = get_data_from_bucket(payload["bucket"], human_key)
            print(f"Human data for page {page_number}:", temp_data)
            
            # Store A2I response
            a2i_responses[f"page_{page_number}_human"] = temp_data
            
            # Check if we have structure map in the human data
            if 'structure_map' in temp_data:
                # If we have structure map, reconstruct the original format
                if 'all_fields' in temp_data:
                    reconstructed_data = reconstruct_original_format(
                        temp_data['all_fields'], 
                        temp_data['structure_map']
                    )
                    a2i_responses[f"page_{page_number}_human_reconstructed"] = reconstructed_data
            
            datakeyhuman, datavaluehuman = create_csv(temp_data, "human", page_number)
            all_human_keys.append(datakeyhuman)
            all_human_values.append(datavaluehuman)
            processed_files.append(human_key)
    
    # Combine all data - AI first, then human
    combined_keys = ",".join(all_ai_keys + all_human_keys)
    combined_values = ",".join(all_ai_values + all_human_values)
    
    # Create the final CSV content
    data = combined_keys + "\n" + combined_values
    
    # Write CSV to S3
    bucket, key = write_to_s3(data, payload, payload["key"], image_keys)
    upload_response = {"bucket": bucket, "key": key}
    
    # Extract a meaningful name from the original upload key for JSON files
    if "/" in payload["key"]:
        filename = payload["key"].split("/")[-1].split(".")[0]
    else:
        filename = payload["key"].split(".")[0]
    
    # Format image_keys for the filename
    if image_keys and isinstance(image_keys, list):
        image_keys_str = "-".join([str(k) for k in image_keys])
    else:
        image_keys_str = "unknown"
    
    # Write original responses to S3
    original_responses_key = f"complete/{payload['id']}-{filename}-pages-{image_keys_str}-original-responses.json"
    write_json_to_s3(original_responses, payload["bucket"], original_responses_key)
    
    # Write A2I responses to S3
    a2i_responses_key = f"complete/{payload['id']}-{filename}-pages-{image_keys_str}-a2i-responses.json"
    write_json_to_s3(a2i_responses, payload["bucket"], a2i_responses_key)
    
    # Add the JSON file paths to the upload response
    upload_response["original_responses_key"] = original_responses_key
    upload_response["a2i_responses_key"] = a2i_responses_key
    
    return data, upload_response, processed_files

def get_base_image_keys(bucket, keys):
    temp = []
    for key in keys:
        if "/human/output.json" in key:
            temp.append(key[:key.rfind("/human/output.json")])
        if "/ai/output.json" in key:
            temp.append(key[:key.rfind("/ai/output.json")])
    return list(dict.fromkeys(temp))

def get_extension(s):
    return s.split('.')[-1]

def get_all_possible_files(event):
    files = []
    payload = {}

    payload["bucket"] = event["bucket"]
    payload["id"] = event["id"]
    payload["key"] = event["key"]
    if "a2i_result" in event and "a2iinput" in event["a2i_result"]:
        payload["a2iinput"] = event["a2i_result"]["a2iinput"]
    else:
        payload["a2iinput"] = "notnone"

    extension = os.path.splitext(event["key"])[1].lower()[1:]
    
    # If extension is pdf, use png, otherwise use the provided extension
    file_extension = "png" if extension.lower() == "pdf" else extension

    image_keys = None
    
    # Try different paths to find image_keys
    if "image_keys" in event:
        image_keys = event["image_keys"]
    elif "confidence_check" in event and "Payload" in event["confidence_check"] and "image_keys" in event["confidence_check"]["Payload"]:
        image_keys = event["confidence_check"]["Payload"]["image_keys"]

    # Default to empty list if image_keys is still not found
    if image_keys is None:
        image_keys = []
        print("WARNING: Could not find image_keys in any expected location")

    for item in image_keys:
        # Check type and handle appropriately
        if isinstance(item, int):
            print(f"Converting integer item {item} to string")
            item = str(item)

        if item == "single_image":
            base_key = f"wip/{payload['id']}/single_image/0.{file_extension}"
        else:
            base_key = f"wip/{payload['id']}/{item}.{file_extension}"
        
        possible_ai_output_key = base_key + "/ai/output.json"
        possible_human_output_key = base_key + "/human/output.json"
        print(possible_ai_output_key)
        print(possible_human_output_key)
        
        s3 = boto3.resource('s3')
        try:
            s3.Object(event["bucket"], possible_ai_output_key).load()
            files.append(possible_ai_output_key)
        except botocore.exceptions.ClientError as e:
            pass

        try:
            s3.Object(event["bucket"], possible_human_output_key).load()
            files.append(possible_human_output_key)
        except botocore.exceptions.ClientError as e:
            pass
            
    return files, payload, image_keys

def gather_and_combine_data(event):
    keys, payload, image_keys = get_all_possible_files(event)
    print(keys)
    print(payload)    
    base_image_keys = get_base_image_keys(payload["bucket"], keys)
    print("base_image_keys", base_image_keys)
    
    # Sort base_image_keys to ensure consistent page ordering
    base_image_keys.sort()
    
    data, s3outputpath, processed_keys = curate_data(base_image_keys, payload, image_keys)
    return data, s3outputpath, payload, processed_keys
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
import re

def lambda_handler(event, context):
    """
    Lambda function to clean up two specific folders:
    1. wip/{document_id}/
    2. The BDA job folder from job_metadata_uri
    
    Expected event format:
    {
        "bucket": "multipagepdfbda-multipagepdfbda61c279ea-cdnthyfgz6ya",
        "id": "8c8d1a426c38495dae9aa667741f585e",
        "bda_results": {
            "job_metadata_uri": "s3://multipagepdfbda-multipagepdfbda61c279ea-cdnthyfgz6ya/output/aef66365-89bc-420f-9a99-c0d13ab753d1/job_metadata.json"
        }
    }
    """
    print("Received cleanup request:", event)
    
    # Extract required parameters
    bucket = event.get("bucket")
    document_id = event.get("id")
    
    if not bucket or not document_id:
        return {
            "statusCode": 400,
            "body": "Missing required parameters: bucket and id"
        }
    
    # Track deleted files count
    total_deleted = 0
    
    # 1. Delete wip/{document_id}/ folder
    wip_folder = f"wip/{document_id}/"
    wip_deleted = delete_folder(bucket, wip_folder)
    total_deleted += wip_deleted
    print(f"Deleted {wip_deleted} files from {wip_folder}")
    
    # 2. Delete BDA job folder from job_metadata_uri
    if event.get("bda_results") and event["bda_results"].get("job_metadata_uri"):
        bda_job_uri = event["bda_results"]["job_metadata_uri"]
        print(f"Received BDA job metadata URI: {bda_job_uri}")
        bda_job_folder = extract_bda_job_folder(bda_job_uri)
        print(f"Extracted BDA job folder: {bda_job_folder}")
        
        if bda_job_folder:
            bda_deleted = delete_folder(bucket, bda_job_folder)
            total_deleted += bda_deleted
            print(f"Deleted {bda_deleted} files from {bda_job_folder}")
    
    return {
        "statusCode": 200,
        "body": f"Successfully deleted {total_deleted} files"
    }

def extract_bda_job_folder(job_uri):
    """
    Extract the BDA job folder path from the job_metadata_uri
    
    Example: 
    s3://bucket/output/aef66365-89bc-420f-9a99-c0d13ab753d1/job_metadata.json
    -> output/aef66365-89bc-420f-9a99-c0d13ab753d1/
    """
    try:
        parts = job_uri.split('/')
        # Remove the last part (job_metadata.json)
        folder_path = '/'.join(parts[3:-1])
        return folder_path
    except Exception as e:
        print(f"Error in fallback extraction: {str(e)}")
    
    return None

def delete_folder(bucket, prefix):
    """
    Delete all files in a folder prefix.
    
    Args:
        bucket: S3 bucket name
        prefix: Folder prefix to delete (e.g., "wip/document-id/")
    
    Returns:
        Number of files deleted
    """
    s3_client = boto3.client('s3')
    deleted_count = 0
    
    # Use pagination to handle folders with many files
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    
    for page in pages:
        if 'Contents' not in page:
            # No objects found with this prefix
            continue
        
        # Collect objects to delete (up to 1000 per batch)
        objects_to_delete = [{'Key': obj['Key']} for obj in page['Contents']]
        
        if objects_to_delete:
            try:
                # Delete the batch of objects
                response = s3_client.delete_objects(
                    Bucket=bucket,
                    Delete={'Objects': objects_to_delete}
                )
                
                # Count deleted objects
                if 'Deleted' in response:
                    deleted_count += len(response['Deleted'])
                
                # Log any errors
                if 'Errors' in response and response['Errors']:
                    for error in response['Errors']:
                        print(f"Error deleting {error['Key']}: {error['Code']} - {error['Message']}")
                        
            except Exception as e:
                print(f"Error deleting objects in {prefix}: {str(e)}")
    
    return deleted_count
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


import boto3
import json

def lambda_handler(event, context):
    print(event)    
    payload = event.get('Payload', {})
    print(f"payload: {payload}")
    bda_results = payload.get('bda_results', {})
    print(f"bda_results: {bda_results}")
    job_metadata_uri = bda_results.get('job_metadata_uri')
    
    if not job_metadata_uri:
        return {
            'segment_uris': [],
            'error': 'No BDA results found'
        }
    
    # Parse S3 URI
    s3_uri_parts = job_metadata_uri.replace('s3://', '').split('/')
    bucket = s3_uri_parts[0]
    key = '/'.join(s3_uri_parts[1:])
    
    # Get job metadata from S3
    s3 = boto3.client('s3')
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        job_metadata = json.loads(response['Body'].read().decode('utf-8'))
        
        # Extract all segment metadata URIs
        segment_uris = []
        for segment in job_metadata.get('output_metadata', []):
            for segment_metadata in segment.get('segment_metadata', []):
                if 'custom_output_status' in segment_metadata and segment_metadata['custom_output_status'] == 'MATCH':
                    # Add the direct URI to the list
                    segment_uris.append(segment_metadata['custom_output_path'])
        
        return {
            'segment_uris': segment_uris
        }
        
    except Exception as e:
        print(f"Error retrieving job metadata: {str(e)}")
        return {
            'segment_uris': [],
            'error': f'Error retrieving job metadata: {str(e)}'
        }
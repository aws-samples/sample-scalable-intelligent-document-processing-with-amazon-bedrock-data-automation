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
import copy

def lambda_handler(event, context):
    # Configuration
    CONFIDENCE_THRESHOLD = float(os.environ.get('CONFIDENCE_THRESHOLD', '0.7'))
    
    # Get segment URI from input
    segment_uri = event.get('segment_uri')
    
    if not segment_uri:
        return {
            'needs_a2i': True,  # Default to A2I if no segment URI
            'reason': 'No segment URI provided',
            'page_index': 0
        }
    
    # Parse S3 URI
    s3_uri_parts = segment_uri.replace('s3://', '').split('/')
    bucket = s3_uri_parts[0]
    key = '/'.join(s3_uri_parts[1:])
    
    # Extract segment index from the path
    # Assuming path format: .../custom_output/{segment_index}/result.json
    path_parts = key.split('/')
    segment_index = 0
    for i, part in enumerate(path_parts):
        if part == 'custom_output' and i+1 < len(path_parts):
            try:
                segment_index = int(path_parts[i+1])
                break
            except:
                pass
    
    # Get custom output from S3
    s3 = boto3.client('s3')
    try:
        custom_response = s3.get_object(Bucket=bucket, Key=key)
        custom_output = json.loads(custom_response['Body'].read().decode('utf-8'))
        
        # Initialize variables
        needs_a2i = False
        all_fields = []
        page_index = segment_index
        inference_result = None
        image_keys = []  # Initialize image_keys as an empty list
        
        # Store inference_result if available
        if 'inference_result' in custom_output:
            inference_result = custom_output['inference_result']
            print(f"Found inference_result in custom output")
        
        # Store multi-page document information if available
        if 'split_document' in custom_output:
            # Extract page_indices
            if 'page_indices' in custom_output['split_document']:
                image_keys = custom_output['split_document']['page_indices']
                if len(image_keys) > 0:
                    page_index = image_keys[0]
                
                print(f"Multi-page document detected with pages: {image_keys}")
        
        # Process all fields in explainability_info
        if 'explainability_info' in custom_output:
            field_results = process_explainability_info(custom_output['explainability_info'], CONFIDENCE_THRESHOLD)
            
            # Check if any field is below threshold
            if field_results['has_low_confidence']:
                needs_a2i = True
            
            # Store all fields with complete information
            all_fields = field_results['all_fields']
        
        # Prepare result for A2I
        result = {
            'needs_a2i': needs_a2i,
            'all_fields': all_fields,
            'page_index': page_index,
            'segment_index': segment_index,
            'image_keys': image_keys,  # Add the image_keys to the result
            'a2i_input': "none"
        }
        
        # Add inference_result to the result if available
        if inference_result:
            result['inference_result'] = inference_result
        
        # If A2I is needed and we have custom output, prepare the A2I input
        if needs_a2i:
            # Add taskObject (S3 path to the document)
            s3_document_path = event.get('id', '')
            if s3_document_path:
                bucket_name = event.get('bucket', '')
                key_name = event.get('key', '')
                if bucket_name and key_name:
                    custom_output["taskObject"] = f"s3://{bucket_name}/{key_name}"
            
            # Create A2I input content
            a2i_input = create_a2i_input_content(custom_output, all_fields)
            result['a2i_input'] = a2i_input
        
        return result
    
    except Exception as e:
        print(f"Error processing custom output: {str(e)}")
        return {
            'needs_a2i': True,
            'reason': f'Error processing custom output: {str(e)}',
            'page_index': segment_index
        }

def create_a2i_input_content(custom_output, all_fields):
    """
    Create the input content for A2I workflow based on the custom output and processed fields
    """
    input_content = {
        "taskObject": custom_output.get("taskObject", ""),
        "labels": []
    }
    
    # Create labels from all_fields
    for field in all_fields:
        label_info = {
            "name": field["field_name"],
            "value": field["value"],
            "confidence": field["confidence"],
            "page": field["page"],
            "boundingBox": get_bounding_box_from_geometry(field["geometry"]),
            "vertices": get_vertices_from_geometry(field["geometry"])
        }
        input_content["labels"].append(label_info)
    
    return input_content

def get_bounding_box_from_geometry(geometry):
    """Extract bounding box from geometry if available"""
    if geometry and isinstance(geometry, list) and len(geometry) > 0:
        return geometry[0].get("boundingBox")
    return None

def get_vertices_from_geometry(geometry):
    """Extract vertices from geometry if available"""
    if geometry and isinstance(geometry, list) and len(geometry) > 0:
        return geometry[0].get("vertices")
    return None

def process_explainability_info(explainability_info, threshold):
    """
    Process all fields in the explainability_info structure.
    Returns information about all fields with complete details and path information
    to facilitate reconstruction of the original structure.
    """
    result = {
        'has_low_confidence': False,
        'all_fields': [],
        'structure_map': {}  # Stores information about the structure for reconstruction
    }
    
    # Process each explainability info section
    for section_idx, section in enumerate(explainability_info):
        # For handling nested structures like immunization_records
        for field_name, field_data in section.items():
            # If this is a list (like immunization_records)
            if isinstance(field_data, list):
                # Record structure information
                result['structure_map'][field_name] = {
                    'type': 'array',
                    'length': len(field_data),
                    'section_idx': section_idx
                }
                
                for i, item in enumerate(field_data):
                    # First pass: find page number for this record
                    record_page = None
                    for sub_field, sub_data in item.items():
                        if isinstance(sub_data, dict) and 'geometry' in sub_data:
                            page = get_page_from_geometry(sub_data['geometry'])
                            if page != 1:  # If we found a non-default page
                                record_page = page
                                break
                    
                    # Record item structure
                    result['structure_map'][f"{field_name}[{i}]"] = {
                        'type': 'object',
                        'parent': field_name,
                        'index': i
                    }
                    
                    # Second pass: process all fields with the correct page number
                    for sub_field, sub_data in item.items():
                        if isinstance(sub_data, dict) and 'confidence' in sub_data:
                            field_path = f"{field_name}[{i}].{sub_field}"
                            path_components = {
                                'root': field_name,
                                'array_index': i,
                                'field': sub_field
                            }
                            
                            geometry = None
                            
                            # Extract geometry and page information
                            if 'geometry' in sub_data:
                                geometry = sub_data['geometry']
                                page = get_page_from_geometry(geometry)
                                # Remove page from geometry
                                geometry = remove_page_from_geometry(geometry)
                            else:
                                # Use the record's page number if available
                                page = record_page if record_page is not None else 1
                            
                            confidence = sub_data['confidence']
                            field_info = {
                                'field_name': field_path,
                                'display_name': sub_field,  # For display in A2I
                                'value': sub_data.get('value', ''),
                                'confidence': confidence,
                                'page': page - 1,  # Adjust to zero-based page numbering
                                'geometry': geometry,
                                'path_components': path_components,
                                'field_type': 'simple',
                                'parent_type': 'array_item'
                            }
                            
                            result['all_fields'].append(field_info)
                            
                            # Check if confidence is below threshold and log it
                            if confidence < threshold:
                                print(f"Low confidence field: {field_path}, confidence: {confidence}, threshold: {threshold}")
                                result['has_low_confidence'] = True
            
            # If this is a nested structure with multiple fields
            elif isinstance(field_data, dict) and not ('confidence' in field_data):
                # Record structure information
                result['structure_map'][field_name] = {
                    'type': 'object',
                    'section_idx': section_idx
                }
                
                # First pass: find page number for this record
                record_page = None
                for sub_field, sub_data in field_data.items():
                    if isinstance(sub_data, dict) and 'geometry' in sub_data:
                        page = get_page_from_geometry(sub_data['geometry'])
                        if page != 1:  # If we found a non-default page
                            record_page = page
                            break
                
                # Second pass: process all fields with the correct page number
                for sub_field, sub_data in field_data.items():
                    if isinstance(sub_data, dict) and 'confidence' in sub_data:
                        field_path = f"{field_name}.{sub_field}"
                        path_components = {
                            'root': field_name,
                            'field': sub_field
                        }
                        
                        geometry = None
                        
                        # Extract geometry and page information
                        if 'geometry' in sub_data:
                            geometry = sub_data['geometry']
                            page = get_page_from_geometry(geometry)
                            # Remove page from geometry
                            geometry = remove_page_from_geometry(geometry)
                        else:
                            # Use the record's page number if available
                            page = record_page if record_page is not None else 1
                        
                        confidence = sub_data['confidence']
                        field_info = {
                            'field_name': field_path,
                            'display_name': sub_field,  # For display in A2I
                            'value': sub_data.get('value', ''),
                            'confidence': confidence,
                            'page': page - 1,  # Adjust to zero-based page numbering
                            'geometry': geometry,
                            'path_components': path_components,
                            'field_type': 'simple',
                            'parent_type': 'object'
                        }
                        
                        result['all_fields'].append(field_info)
                        
                        # Check if confidence is below threshold and log it
                        if confidence < threshold:
                            print(f"Low confidence field: {field_path}, confidence: {confidence}, threshold: {threshold}")
                            result['has_low_confidence'] = True
            
            # If this is a simple field
            elif isinstance(field_data, dict) and 'confidence' in field_data:
                # Record structure information
                result['structure_map'][field_name] = {
                    'type': 'simple',
                    'section_idx': section_idx
                }
                
                page = 1
                geometry = None
                
                # Extract geometry and page information
                if 'geometry' in field_data:
                    geometry = field_data['geometry']
                    page = get_page_from_geometry(geometry)
                    # Remove page from geometry
                    geometry = remove_page_from_geometry(geometry)
                
                confidence = field_data['confidence']
                field_info = {
                    'field_name': field_name,
                    'display_name': field_name,  # For display in A2I
                    'value': field_data.get('value', ''),
                    'confidence': confidence,
                    'page': page - 1,  # Adjust to zero-based page numbering
                    'geometry': geometry,
                    'path_components': {
                        'root': field_name
                    },
                    'field_type': 'simple',
                    'parent_type': 'root'
                }
                
                result['all_fields'].append(field_info)
                
                # Check if confidence is below threshold and log it
                if confidence < threshold:
                    print(f"Low confidence field: {field_name}, confidence: {confidence}, threshold: {threshold}")
                    result['has_low_confidence'] = True
    
    return result

def remove_page_from_geometry(geometry):
    """
    Remove the page information from geometry data.
    Returns a copy of the geometry with page information removed.
    """
    if not geometry or not isinstance(geometry, list):
        return geometry
    
    # Create a deep copy of the geometry to avoid modifying the original
    geometry_copy = copy.deepcopy(geometry)
    
    # Remove the page field from each geometry item
    for geo_item in geometry_copy:
        if 'page' in geo_item:
            del geo_item['page']
    
    return geometry_copy

def get_page_from_geometry(geometry):
    """
    Extract page information from geometry data.
    Returns the page number or 1 if not found.
    """
    if not geometry or not isinstance(geometry, list):
        return 1
    
    for geo_item in geometry:
        if 'page' in geo_item:
            return geo_item['page']
    
    # Default to page 1 if no page information is found
    return 1
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
#  * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE hSOFTWARE.
#  */

# -------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------
# ~ ENTER SAGEMAKER AUGMENTED AI WORKFLOW ARN HERE:
SAGEMAKER_WORKFLOW_AUGMENTED_AI_ARN_EV = "arn:aws:sagemaker:us-west-2:381491830521:flow-definition/bda-workflow"

# -------------------------------------------------------------------------------------------
# ---cdk----------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------

import aws_cdk as cdk

from aws_cdk import (
    Stack,
    aws_s3,
    aws_lambda,
    aws_iam,
    aws_s3_notifications,
    aws_dynamodb,
    aws_stepfunctions,
    aws_stepfunctions_tasks,
    aws_sqs,
    aws_lambda_event_sources,
    aws_events,
    aws_kms,
    aws_events_targets,
    aws_logs,  
    Aspects,
)
from constructs import Construct
from cdk_nag import NagSuppressions 


class multipagepdfbdaStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        services = self.create_services()
        self.create_events(services)

    def create_state_machine(self, services):
        # Lambda tasks
        task_invoke_bda = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            "Invoke Bedrock Data Automation",
            lambda_function=services["lambda"]["invoke_bda"],
            payload_response_only=True,
            result_path="$.bda_results",
        )
        
        task_image_resize = aws_stepfunctions_tasks.LambdaInvoke(
            self, 
            "Image Resize to < 5 MB", 
            lambda_function=services["lambda"]["imageresize"], 
            result_path="$.Input",
        )
        
        # Extract segment metadata task
        task_extract_metadata = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            "Extract Segment Metadata",
            lambda_function=services["lambda"]["extractmetadata"],
            payload=aws_stepfunctions.TaskInput.from_object({
                "FunctionName": services["lambda"]["extractmetadata"].function_arn,
                "Payload.$": "$"
            }),
            result_path="$.segment_metadata",
        )
        
        # Cleanup task for the new end state
        task_cleanup = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            "Cleanup Temporary Files",
            lambda_function=services["lambda"]["cleans3files"],
            result_path="$.cleanup_result",
        )
        
        # Define the nested map iterator
        check_confidence_task = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            "Check Segment Confidence",
            lambda_function=services["lambda"]["check_confidence"],
            payload=aws_stepfunctions.TaskInput.from_object({
                "id.$": "$.id",
                "bucket.$": "$.bucket",
                "key.$": "$.key",
                "extension.$": "$.extension",
                "segment_uri.$": "$.segment_uri"
            }),
            result_path="$.confidence_result",
        )
        
        convert_pdf_task = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            "Convert PDF Page to PNG",
            lambda_function=services["lambda"]["pngextract"],
            payload=aws_stepfunctions.TaskInput.from_object({
                "id.$": "$.id",
                "bucket.$": "$.bucket",
                "key.$": "$.key",
                "page_index.$": "$.confidence_result.Payload.page_index",
                "segment_uri.$": "$.segment_uri"
            }),
            result_path="$.conversion_result",
        )
        
        perform_bedrock_a2i = aws_stepfunctions_tasks.SqsSendMessage(
            self,
            "Perform Bedrock Data Automation and A2I",
            queue=services["bedrock_sqs"],
            message_body=aws_stepfunctions.TaskInput.from_object({
                "token": aws_stepfunctions.JsonPath.task_token,
                "id.$": "$.id",
                "bucket.$": "$.bucket",
                "key.$": "$.key",
                "a2iinput.$": "$.confidence_result.Payload.a2i_input",
                "wip_key.$": "$.confidence_result.Payload.page_index",
                "inference_result.$": "$.confidence_result.Payload.inference_result",
                "image_keys.$": "$.confidence_result.Payload.image_keys"
            }),
            integration_pattern=aws_stepfunctions.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            result_path="$.a2i_result",
        )
        
        wrapup_task = aws_stepfunctions_tasks.LambdaInvoke(
            self, 
            "Wrapup and Clean A2I", 
            lambda_function=services["lambda"]["wrapup"],
            payload=aws_stepfunctions.TaskInput.from_object({
                "id.$": "$.id",
                "bucket.$": "$.bucket",
                "key.$": "$.key",
                "a2i_result.$": "$.a2i_result",
                "image_keys.$": "$.confidence_result.Payload.image_keys",
                "segment_index.$": "$.confidence_result.Payload.segment_index",
                "page_index.$": "$.confidence_result.Payload.page_index",
                "inference_result.$": "$.confidence_result.Payload.inference_result"
            }),
            result_path="$.wrapup_result",
        )
        
        # Define the document need A2I choice
        need_a2i_choice = aws_stepfunctions.Choice(self, "Does Document Need A2I?")
        
        # Combined condition for both needs_a2i=true AND extension=pdf
        pdf_and_needs_a2i_condition = aws_stepfunctions.Condition.and_(
            aws_stepfunctions.Condition.boolean_equals("$.confidence_result.Payload.needs_a2i", True),
            aws_stepfunctions.Condition.string_equals("$.extension", "pdf")
        )
        
        need_a2i_choice.when(
            pdf_and_needs_a2i_condition,
            convert_pdf_task
        )
        
        need_a2i_choice.when(
            aws_stepfunctions.Condition.boolean_equals("$.confidence_result.Payload.needs_a2i", True),
            perform_bedrock_a2i
        )
        
        need_a2i_choice.otherwise(perform_bedrock_a2i)
        
        # Set up the iterator chain
        check_confidence_task.next(need_a2i_choice)
        convert_pdf_task.next(perform_bedrock_a2i)
        perform_bedrock_a2i.next(wrapup_task)
        
        # Set up the map state for processing segments
        process_segments_map = aws_stepfunctions.Map(
            self,
            "Process Segments Map",
            items_path="$.segment_metadata.Payload.segment_uris",
            result_path="$.map_results",
            parameters={
                "id.$": "$.id",
                "bucket.$": "$.bucket",
                "key.$": "$.key",
                "extension.$": "$.extension",
                "segment_uri.$": "$$.Map.Item.Value"
            }
        )
        
        # Set the iterator after creating the Map
        process_segments_map.iterator(aws_stepfunctions.Chain.start(check_confidence_task))
        # Main choice state for document type
        pdf_or_image_choice = aws_stepfunctions.Choice(self, "PDF or Image?")
        pdf_or_image_choice.when(
            aws_stepfunctions.Condition.string_equals("$.extension", "pdf"),
            task_invoke_bda
        )
        pdf_or_image_choice.when(
            aws_stepfunctions.Condition.string_equals("$.extension", "png"), 
            task_image_resize
        )
        pdf_or_image_choice.when(
            aws_stepfunctions.Condition.string_equals("$.extension", "jpg"), 
            task_image_resize
        )
    
        # Connect top level flow
        task_invoke_bda.next(task_extract_metadata)
        task_extract_metadata.next(process_segments_map)
        process_segments_map.next(task_cleanup)
        task_image_resize.next(task_invoke_bda)
    
        # Creates the Step Functions with proper flow
        multipagepdfbda_sf = aws_stepfunctions.StateMachine(
            scope=self,
            id="multipagepdfbda_stepfunction",
            state_machine_name="multipagepdfbda_stepfunction",
            role=services["sf_iam_roles"]["sfunctions"],
            definition=pdf_or_image_choice,
            tracing_enabled=True,
            logs=aws_stepfunctions.LogOptions(
                destination=services["sf_log_group"],
                level=aws_stepfunctions.LogLevel.ALL
            )
        )
        
        return multipagepdfbda_sf	
    
    def create_iam_role_for_lambdas(self, services):
        iam_roles = {}

        names = ["kickoff", "pngextract", "analyzepdf", "humancomplete", "wrapup","imageresize","invoke_bda","check_confidence","extractmetadata","cleans3files"]
        for name in names:
            iam_roles[name] = aws_iam.Role(
                scope=self,
                id="multipagepdfbda_lam_role_" + name,
                assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            )

        iam_roles["kickoff"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services['sf_sqs'].queue_arn,services['bedrock_sqs'].queue_arn],
                actions=[
                    "sqs:DeleteMessage",
                    "sqs:ReceiveMessage",
                ],
            )
        )

        iam_roles["kickoff"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:states:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:stateMachine:multipagepdfbda_stepfunction"], 
                actions=[
                    "states:StartExecution",
                ],
            )
        )        
        

        iam_roles["kickoff"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],   
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["kickoff"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_kickoff:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )         
        
        iam_roles["imageresize"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )

        iam_roles["imageresize"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],  
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["imageresize"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_imageresize:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )

        iam_roles["extractmetadata"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],  
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["extractmetadata"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_extractmetadata:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )

        iam_roles["extractmetadata"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )
        
        iam_roles["cleans3files"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],  
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["cleans3files"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_cleans3files:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )

        iam_roles["cleans3files"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                    "s3:DeleteObject"
                ],
            )
        )         
        
        iam_roles["pngextract"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )

        iam_roles["pngextract"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"], 
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["pngextract"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_pngextract:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        ) 

        iam_roles["invoke_bda"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"], 
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["invoke_bda"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_invoke_bda:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        ) 

        iam_roles["invoke_bda"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )        

        iam_roles["invoke_bda"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:bedrock:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:data-automation-project/*",
                           f"arn:aws:bedrock:us-east-1:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-east-2:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-west-1:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-west-2:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:data-automation-invocation/*",
                           ],
                actions=[
                    "bedrock:InvokeDataAutomationAsync","bedrock:ListDataAutomationProjects","bedrock:GetDataAutomationStatus"
                ],
            )
        )

        iam_roles["check_confidence"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"], 
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["check_confidence"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_check_confidence:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        ) 

        iam_roles["check_confidence"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )            
        
        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:bedrock:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:data-automation-project/*",
                           f"arn:aws:bedrock:us-east-1:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-east-2:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-west-1:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1",
                           f"arn:aws:bedrock:us-west-2:{cdk.Stack.of(self).account}:data-automation-profile/us.data-automation-v1"
                           ],
                actions=[
                    "bedrock:InvokeDataAutomationAsync","bedrock:ListDataAutomationProjects"
                ],
            )
        )        
        
        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:dynamodb:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:table/{services['ddbtable_multia2ipdf_callback'].table_name}"],
                actions=[
                    "dynamodb:PutItem",
                ],
            )
        )        

        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services['sf_sqs'].queue_arn,services['bedrock_sqs'].queue_arn],
                actions=[
                    "sqs:DeleteMessage",
                    "sqs:ReceiveMessage", 
                    "sqs:ChangeMessageVisibility",
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl",
                ],
            )
        )          
        
        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:states:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:stateMachine:multipagepdfbda_stepfunction"], 
                actions=[
                    "states:SendTaskSuccess",
                ],
            )
        )          


        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],   
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        )

        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:sagemaker:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:flow-definition/*"],
                actions=[
                    "sagemaker:StartHumanLoop",
                ],
            )
        )        

        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_analyzepdf:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )
        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:dynamodb:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:table/{services['ddbtable_multia2ipdf_callback'].table_name}"],
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                ],
            )
        )        

        iam_roles["analyzepdf"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )         

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:dynamodb:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:table/{services['ddbtable_multia2ipdf_callback'].table_name}/index/document_id-index"],
                actions=[
                    "dynamodb:Query",
                ],
            )
        )
        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:dynamodb:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:table/{services['ddbtable_multia2ipdf_callback'].table_name}"],
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:UpdateItem"
                ],
            )
        )          

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:states:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:stateMachine:multipagepdfbda_stepfunction"], 
                actions=[
                    "states:SendTaskSuccess",
                ],
            )
        )         

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"],   
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_humancomplete:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )  

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                ],
            )
        )

        iam_roles["humancomplete"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:dynamodb:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:table/{services['ddbtable_multia2ipdf_callback'].table_name}"],
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                ],
            )
        )          

        iam_roles["wrapup"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services["main_s3_bucket"].bucket_arn,  f"{services['main_s3_bucket'].bucket_arn}/*"],
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:Object",
                    "s3:DeleteObject",
                    "s3:ListBucket",                    
                ],
            )
        )        

        iam_roles["wrapup"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:*"], 
                actions=[ 
                    "logs:CreateLogGroup",
                ],
            )
        ) 

        iam_roles["wrapup"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/lambda/multipagepdfbda_wrapup:*"],   
                actions=[ 
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",                    
                ],
            )
        )
        
        return iam_roles
        
    def create_iam_role_for_stepfunction(self, services):
        iam_roles = {}

        names = ["sfunctions"]

        for name in names:
            iam_roles[name] = aws_iam.Role(
                scope=self,
                id="multipagepdfbda_lam_role_" + name,
                assumed_by=aws_iam.ServicePrincipal("states.amazonaws.com"),
            )

        iam_roles["sfunctions"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[services['bedrock_sqs'].queue_arn],
                actions=[
                    "sqs:SendMessage"
                ],
            )
        )

        iam_roles["sfunctions"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_imageresize",
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_pngextract",
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_wrapup",
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_humancomplete",
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_analyzepdf",
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_kickoff"
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_invoke_bda",                
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_check_confidence",  
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_cleans3files",                
                f"arn:aws:lambda:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:function:multipagepdfbda_extractmetadata"                    
                
                ], 
                actions=[
                    "lambda:InvokeFunction",
                ],
            )
        )        
        
        iam_roles["sfunctions"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=[f"arn:aws:logs:{cdk.Stack.of(self).region}:{cdk.Stack.of(self).account}:log-group:/aws/stepfunctions/multipagepdfbda_stepfunction_logs:*"],   
                actions=[ 
                    "logs:CreateLogDelivery",
                    "logs:DeleteLogDelivery",   
                    "logs:DescribeLogGroups",
                    "logs:DescribeResourcePolicies",    
                    "logs:GetLogDelivery",
                    "logs:ListLogDeliveries",    
                    "logs:PutResourcePolicy",
                    "logs:UpdateLogDelivery",                        
                ],
            )
        ) 

        iam_roles["sfunctions"].add_to_policy(
            statement=aws_iam.PolicyStatement(
                resources=["*"],   
                actions=[ 
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",   
                    "xray:PutTelemetryRecords",
                    "xray:PutTraceSegments",    
                ],
            )
        )         
        
        NagSuppressions.add_resource_suppressions(
            [
                iam_roles["sfunctions"],
            ],
            [
                {
                    'id': 'W12',
                    'reason': 'This is created for a POC. Customer while deploying this for production will restrict the resource for xray policy',
                },
                {
                    'id': 'W76',
                    'reason': 'This is created for a POC. Customer while deploying this for production will create multiple policies instead of one',
                }                
            ]
        )

        return iam_roles


        
    def create_lambda_functions(self, services):
        lambda_functions = {}
        

    # Define a Lambda layer
        my_layer = aws_lambda.LayerVersion(
            self, "sharplayer",
            code=aws_lambda.Code.from_asset( "./deploy_code/multipagepdfbda_imageresize/sharplayer.zip"),  
            compatible_runtimes=[aws_lambda.Runtime.NODEJS_20_X],  
            description="sharplayer" 
        )  
        # Define a boto3  layer
        my_boto3_layer = aws_lambda.LayerVersion(
            self, "boto3layer",
            code=aws_lambda.Code.from_asset( "./deploy_code/layer/"), 
            compatible_runtimes=[aws_lambda.Runtime.PYTHON_3_12], 
            description="bedrock BDA dependencies" 
        )      
        

        lambda_functions["pngextract"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_pngextract",
            function_name="multipagepdfbda_pngextract",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_pngextract/multipagepdfbda_pngextract.jar"
            ),
            handler="Lambda::handleRequest",
            runtime=aws_lambda.Runtime.JAVA_21,
            timeout=cdk.Duration.minutes(15),
            memory_size=3000,
            role=services["iam_roles"]["pngextract"],
        )
        

        lambda_functions["imageresize"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_imageresize",
            function_name="multipagepdfbda_imageresize",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_imageresize/"
            ),
            handler="index.handler",
            runtime=aws_lambda.Runtime.NODEJS_20_X,
            timeout=cdk.Duration.minutes(15),
            layers=[my_layer],
            memory_size=3000,
            role=services["iam_roles"]["imageresize"],
        )        


        lambda_functions["analyzepdf"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_analyzepdf",
            function_name="multipagepdfbda_analyzepdf",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_analyzepdf/"
            ),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(3),
            layers=[my_boto3_layer],
            memory_size=3000,
            role=services["iam_roles"]["analyzepdf"],
            environment={
                "sqs_url": services["bedrock_sqs"].queue_url,
                "ddb_tablename": services["ddbtable_multia2ipdf_callback"].table_name,
                "human_workflow_arn": SAGEMAKER_WORKFLOW_AUGMENTED_AI_ARN_EV,                
            },
        )

        lambda_functions["cleans3files"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_cleans3files",
            function_name="multipagepdfbda_cleans3files",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_cleans3files/"
            ),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(3),
            memory_size=3000,
            role=services["iam_roles"]["cleans3files"],
        ) 
        
        lambda_functions["extractmetadata"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_extractmetadata",
            function_name="multipagepdfbda_extractmetadata",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_extractmetadata/"
            ),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(3),
            memory_size=3000,
            role=services["iam_roles"]["extractmetadata"],
        )           

        lambda_functions["invoke_bda"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_invoke_bda",
            function_name="multipagepdfbda_invoke_bda",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_invokebda/"
            ),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(3),
            layers=[my_boto3_layer],
            memory_size=3000,
            role=services["iam_roles"]["invoke_bda"],
            environment={
                "REGION": cdk.Stack.of(self).region,
                "OUTPUT_PATH": "output",
                "PROJECT_ID": "3badb9d9df2d",  # Have to change this project ID before deploying into the new account          
            },
        ) 

        lambda_functions["check_confidence"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_check_confidence",
            function_name="multipagepdfbda_check_confidence",
            code=aws_lambda.Code.from_asset(
                "./deploy_code/multipagepdfbda_confidence/"
            ),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(3),
            layers=[my_boto3_layer],
            memory_size=3000,
            role=services["iam_roles"]["check_confidence"],
            environment={
                "CONFIDENCE_THRESHOLD": "0.95",
            },
        )         

        names = ["humancomplete", "wrapup"]

        for name in names:
            lambda_functions[name] = aws_lambda.Function(
                scope=self,
                id="multipagepdfbda_" + name,
                function_name="multipagepdfbda_" + name,
                code=aws_lambda.Code.from_asset(
                    "./deploy_code/multipagepdfbda_" + name + "/"
                ),
                handler="lambda_function.lambda_handler",
                runtime=aws_lambda.Runtime.PYTHON_3_12,
                timeout=cdk.Duration.minutes(15),
                memory_size=3000,
                role=services["iam_roles"][name],
                environment={
                    "ddb_tablename": services["ddbtable_multia2ipdf_callback"].table_name,
                },                  
            )


 
        NagSuppressions.add_resource_suppressions(
            [
                lambda_functions["wrapup"],
                lambda_functions["imageresize"],
                lambda_functions["humancomplete"],
                lambda_functions["analyzepdf"],
                lambda_functions["pngextract"],
                lambda_functions["check_confidence"],
                lambda_functions["invoke_bda"],
                lambda_functions["cleans3files"],
                lambda_functions["extractmetadata"],                
            ],
            [
                {
                    'id': 'W89',
                    'reason': 'This is created for a POC. Customer will be deploying this for production will be deploying the lambda functions in the  VPC',
                },
                {
                    'id': 'W58',
                    'reason': 'Lambda functions has permission to write CloudWatch Logs',
                },
                {
                    'id': 'W92',
                    'reason': 'This is created for a POC. Customer will be deploying this for production will  define ReservedConcurrentExecutions to reserve simultaneous execution',
                },                
            ]
        )    
        return lambda_functions
        
      

    def create_events(self, services):
        # kickoff_notification = aws_s3_notifications.LambdaDestination(services["lambda"]["kickoff"])
        extensions = [
            "pdf",
            "pDf",
            "pDF",
            "pdF",
            "PDF",
            "Pdf",
            "png",
            "pNg",
            "pNG",
            "pnG",
            "PNG",
            "Png",
            "jpg",
            "jPg",
            "jPG",
            "jpG",
            "JPG",
            "Jpg",
        ]
        for extension in extensions:
            services["main_s3_bucket"].add_event_notification(
                aws_s3.EventType.OBJECT_CREATED,
                aws_s3_notifications.SqsDestination(services["sf_sqs"]),
                aws_s3.NotificationKeyFilter(prefix="uploads/", suffix=extension),
            )

        services["lambda"]["kickoff"].add_event_source(
            aws_lambda_event_sources.SqsEventSource(services["sf_sqs"], batch_size=1)
        )

        services["lambda"]["analyzepdf"].add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                services["bedrock_sqs"], batch_size=1
            )
        )

        human_complete_target = aws_events_targets.LambdaFunction(
            services["lambda"]["humancomplete"]
        )

        human_review_event_pattern = aws_events.EventPattern(
            source=["aws.sagemaker"],
            detail_type=["SageMaker A2I HumanLoop Status Change"],
        )

        aws_events.Rule(
            self,
            "multipadepdfa2i_HumanReviewComplete",
            event_pattern=human_review_event_pattern,
            targets=[human_complete_target],
        )

    def create_services(self):
        services = {}
        # S3 bucket
        services["main_s3_bucket"] = aws_s3.Bucket(
            self, "multipagepdfbda", removal_policy=cdk.RemovalPolicy.DESTROY,  
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            access_control=aws_s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL
        )
        
 
        services["ddbtable_multia2ipdf_callback"] = aws_dynamodb.Table(
                        self,  "ddbtable_multia2ipdf_callback",
                        partition_key=aws_dynamodb.Attribute(
                            name="jobid", type=aws_dynamodb.AttributeType.STRING
                        ),
                        sort_key=aws_dynamodb.Attribute(
                            name="callback_token", type=aws_dynamodb.AttributeType.STRING
                        ),
                        billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
                        point_in_time_recovery=True,  # Enable backup (Point-in-Time Recovery)
                        removal_policy=cdk.RemovalPolicy.DESTROY,
                        encryption=aws_dynamodb.TableEncryption.AWS_MANAGED  # Use AWS-managed key
        )

        # Add the global secondary index for document_id
        services["ddbtable_multia2ipdf_callback"].add_global_secondary_index(
            index_name="document_id-index",
            partition_key=aws_dynamodb.Attribute(
                name="document_id", type=aws_dynamodb.AttributeType.STRING
            ),
            projection_type=aws_dynamodb.ProjectionType.ALL
        )        

        services["sf_sqs"] = aws_sqs.Queue(
            self,
            "multipagepdfbda_sf_sqs",
            queue_name="multipagepdfbda_sf_sqs",
            visibility_timeout=cdk.Duration.minutes(5),
            encryption=aws_sqs.QueueEncryption.SQS_MANAGED, 
        )

        services["bedrock_sqs"] = aws_sqs.Queue(
            self,
            "multipagepdfbda_bedrock_sqs",
            queue_name="multipagepdfbda_bedrock_sqs",
            visibility_timeout=cdk.Duration.minutes(3),
            encryption=aws_sqs.QueueEncryption.SQS_MANAGED, 
        )
        

        # Create a log group for the Step Functions
        services["sf_log_group"] = aws_logs.LogGroup(
            self,
            "/aws/stepfunctions/multipagepdfbda_stepfunction_logs",
            log_group_name="/aws/stepfunctions/multipagepdfbda_stepfunction_logs",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            retention=aws_logs.RetentionDays.ONE_WEEK,
        )

        services["iam_roles"] = self.create_iam_role_for_lambdas(services)
        services["lambda"] = self.create_lambda_functions(services)
        
        services["sf_iam_roles"] = self.create_iam_role_for_stepfunction(services)

        services["sf"] = self.create_state_machine(services)

        services["lambda"]["kickoff"] = aws_lambda.Function(
            scope=self,
            id="multipagepdfbda_kickoff",
            function_name="multipagepdfbda_kickoff",
            code=aws_lambda.Code.from_asset("./deploy_code/multipagepdfbda_kickoff/"),
            handler="lambda_function.lambda_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            timeout=cdk.Duration.minutes(5),
            memory_size=3000,
            role=services["iam_roles"]["kickoff"],
            environment={
                "sqs_url": services["sf_sqs"].queue_url,
                "state_machine_arn": services["sf"].state_machine_arn,
            },
        )

        NagSuppressions.add_resource_suppressions(
            [
                services["lambda"]["kickoff"]
            ],
            [
                {
                    'id': 'W89',
                    'reason': 'This is created for a POC. Customer will be deploying this for production will be deploying the lambda functions in the  VPC',
                },
                {
                    'id': 'W58',
                    'reason': 'Lambda functions has permission to write CloudWatch Logs',
                },
                {
                    'id': 'W92',
                    'reason': 'This is created for a POC. Customer will be deploying this for production will  define ReservedConcurrentExecutions to reserve simultaneous execution',
                }, 
            ]
        )  
        
        
        NagSuppressions.add_resource_suppressions(
            [
                services["main_s3_bucket"],
            ],
            [
                {
                    'id': 'W51',
                    'reason': 'This is created for a POC. Customer will be deploying this will create the bucket policy',
                },
                {
                    'id': 'W35',
                    'reason': 'This is created for a POC. Customer will be deploying this will have access logging configured',
                }                
            ]
        )           
        
        NagSuppressions.add_resource_suppressions(
            [
                services["sf_sqs"],
                services["bedrock_sqs"]
            ],
            [
                {
                    'id': 'W48',
                    'reason': 'SQS is encrypted using SSE-SQS. Customer will use SSE-KMS when deploying to production',
                }
            ]
        )

        NagSuppressions.add_resource_suppressions(
            [
                services["sf_log_group"]
            ],
            [
                {
                    'id': 'W84',
                    'reason': 'This is created for a POC. Customer will be deploying this for production will enable encryption',
                }
            ]
        )         
        

        return services
        
        

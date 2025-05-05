# Processing  Documents with a Human-in-the-Loop using Amazon Bedrock Data Automation and Amazon A2I


## Prerequisites

1. Node.js
2. Python
3. AWS Command Line Interface (AWS CLI)—for instructions, see [Installing the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-install.html)
4. Create a blueprint and Bedrock Data Autoamtion Project using the steps mentioned in [createbdaproject.md](createbdaproject.md)

## Deployment

The following code deploys the reference implementation in your AWS account. The solution deploys different components, including an S3 bucket, Step Functions, an Amazon Simple Queue Service (Amazon SQS) queue, and AWS Lambda functions using the AWS Cloud Development Kit (AWS CDK), which is an open-source software development framework to model and provision your cloud application resources using familiar programming languages.

1. clone the GitHub repo:
	```
	git clone https://github.com/aws-samples/sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation
	```
2. Execute the following commands to create the sharp npm package:
	```
	mkdir -p ~/environment/sharplayer/nodejs && cd ~/environment/sharplayer/nodejs 
	npm init -y && npm install --arch=x64 --platform=linux sharp 
	cd .. && zip -r sharplayer.zip . 
	cp sharplayer.zip ~/environment/sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation/deploy_code/multipagepdfbda_imageresize/ 
	cd .. && rm -r sharplayer
	```	
3. Change to the repository directory:
	```
	cd sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation
	```
4. Run the following command:
	```
	pip install -r requirements.txt

	```
	
5. Execute the following command to create the required layer for lambda functions:
	```
	cd deploy_code/layer
	pip install -r requirements.txt --target python
	```	
The first time you deploy an AWS CDK app into an environment for a specific AWS account and Region combination, you must install a bootstrap stack. This stack includes various resources that the AWS CDK needs to complete its operations. For example, this stack includes an Amazon Simple Storage Service (Amazon S3) bucket that the AWS CDK uses to store templates and assets during its deployment processes.

6. change to the main directory (sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation). 
	```
	cd ../.. 
	```


7. Open the file `/sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation/multipagepdfbda/multipagepdfbda_stack.py`. Update line 880 with the Bedrock Data Automation (BDA) Project ID that you saved while creating the BDA Project as per steps mentioned in [createbdaproject.md](createbdaproject.md)
	```
	"PROJECT_ID": 
	```

8. To install the bootstrap stack, run the following command:
	```
	cdk bootstrap
	```
9. From the project's root directory, run the following command to deploy the stack:
	```
	cdk deploy
	```
10. Update the cross-origin resource sharing (CORS) for the S3 bucket:
   a. On the Amazon S3 console, choose Buckets in the navigation pane.
   b. Choose the name of the bucket that was created in the AWS CDK deployment step. It should have a name format like multipagepdfbda-multipagepdf-xxxxxxxxx.
   c. Choose Permissions.
   d. In the Cross-origin resource sharing (CORS) section, choose Edit.
   e. In the CORS configuration editor text box, enter the following CORS configuration:

      ```
      [
         {
            "AllowedHeaders": [
               "Authorization"
            ],
            "AllowedMethods": [
               "GET",
               "HEAD"
            ],
            "AllowedOrigins": [
               "*"
            ],
            "ExposeHeaders": [
               "Access-Control-Allow-Origin"
            ]
         }
      ]
      ```
11. Create a private team: https://docs.aws.amazon.com/sagemaker/latest/dg/sms-workforce-create-private-console.html
	
	a. On the SageMaker AI console, navigate to "Labeling workforces" under Ground Truth in the navigation pane.
	b. Select the Private tab and choose "Create private team".
	c. Select "Invite new workers by email".
	d. In the Email addresses box, enter the email addresses for your work team (use your email address for testing).
	e. Provide an organization name and contact email.
	f. Click "Create private team".
	g. After creating the private team, you will receive an email invitation.
	h. Click the invitation link and change your password to become a verified worker for the team.

Your workforce is now set up and ready to create a human review workflow.
	

12. Create a human review workflow: 
	 a. Create a Custom Worker task template using the process mentioned here https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-worker-template-console.html#a2i-create-worker-template-console, use the content from Custom-Template file
		
		1. On the SageMaker AI console, choose Worker task templates under Augmented AI in the navigation pane.
		2. Click "Create template".
		3. In the Template name field, enter a descriptive name for your template and  select Custom for Template type.
		4. Copy the contents from the Custom template file you downloaded from GitHub repo and replace the content in the Template editor section.
		5. Click "Create" to save the template.
		
	 b. Create the human review workflow using the process mentioned here - https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-create-flow-definition.html#a2i-create-human-review-console
	 
		1. On the SageMaker AI console, choose Human review workflows under Augmented AI in the navigation pane.
		2. Click "Create human review workflow.".
		3. In the Workflow settings section, for Name, enter a unique workflow name.
		4. For S3 bucket, enter the S3 bucket that was created in the AWS CDK deployment step. It should have a name format like multipagepdfbda-multipagepdfbda-xxxxxxxxx. This bucket is where Amazon A2I will store the human review results.
		5. For IAM role, choose Create a new role for Amazon A2I to create a role automatically for you.
				I) For S3 buckets you specify, select Specific S3 buckets.
				II) Enter the S3 bucket in the format; for example, s3://multipagepdfbda-multipagepdfbda-xxxxxxxxxx/.
				III) Choose Create.
				iV) You see a confirmation when role creation is complete, and your role is now pre-populated on the IAM role dropdown menu.
		6. For Task type, select Custom.
		7. In the worker task template section, choose the template that you previously created.
		8. For Task Description, enter “Review the extracted content from the document and make changes as needed”.
		9. For Worker types, select Private.
		10. For Private teams, choose the work team you created earlier.
		11. Choose Create.
		
		You’re redirected to the Human review workflows page, where you will see a confirmation message.
		
		In a few seconds, the status of the workflow will be changed to active. Record your new human review workflow ARN, which you use to configure your human loop in a later step.
	 
13. Open the file `/sample-scalable-intelligent-document-processing-with-amazon-bedrock-data-automation/multipagepdfbda/multipagepdfbda_stack.py`. Update line 23 with the ARN of the human review workflow and save the changes

    ```python
    SAGEMAKER_WORKFLOW_AUGMENTED_AI_ARN_EV = ""
    ```

14. Run `cdk deploy` to update the solution with the human review workflow ARN.

## Clean Up

1. First, you'll need to completely empty the S3 bucket that was created.
2. Finally, you'll need to run:
   ```
   cdk destroy
   ```
## Test the solution

1. To test the solution, create a folder called **uploads** in the S3 bucket **multipagepdfbda-multipagepdfbda-xxxxxxxxx** and upload the sample PDF document [child-support-services-enrollment-form-and-driver-license.pdf](assets/documents/child-support-services-enrollment-form-and-driver-license.pdf) provided. For example,   **uploads/child-support-services-enrollment-form-and-driver-license.pdf**
2. On the SageMaker AI console, choose Labeling workforces under Ground Truth in the navigation pane.
3. On the Private tab, choose the link under Labeling portal sign-in URL.

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_10_-_private_team.png" width="800" />


4. Sign in with the account you configured with Amazon Cognito.
5. Select the job you want to complete and choose Start working.

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_10_-_human_review_1.png" width="800" />

6. In the reviewer UI, you will see instructions and the document to work on. You can use the toolbox to zoom in and out, fit image, and reposition the document.
7. This UI is specifically designed for document-processing tasks. On the right side of the preceding screenshot, the extracted data is automatically prefilled with the Amazon Bedrock Data Automation response. As a worker, you can quickly refer to this sidebar to make sure the extracted information is identified correctly.

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_10_-_a2i_console.png" width="800" />

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_12_-_a2i_console_Child_Support_enrollment_form_a2i.png" width="800" />

8. When you complete the human review for all pages, you will find three different files in the **complete** folder for each document. Since the uploaded document contains two separate documents (1. Driver's License and 2. Child Support Services Enrollment Form), you will have a total of six files:
	1. Files ending with "bda-responses.json" contain the data response from BDA in JSON format.
	2. Files ending with "human-responses.json" contain the data from the human review response in JSON format.
	3. Files ending with "output.csv" contain both the BDA and human responses in CSV format.


## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

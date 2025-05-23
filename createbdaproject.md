# Instructions to create Bedrock Data Automation Blueprint and Project

For this solution, we will be processing a PDF file which has 2 documents - 
1) Child Support Services Enrollment Form
2) Driver License using Bedrock Data Automation (BDA).
   
We will use BDA to identify each document, and then to extract the data we need for downstream processing

## Step 1 : Create BDA Project

We will next create a project within BDA.

* Navigate to AWS Console
* Search for Bedrock in the "Services" search bar
* Once in the Bedrock console, click on the "Projects" menu under Data Automation.  
* Then click the “Create Project” button
* Name the project “my-idpdemo-project”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_1_-_BDA_Projects.png" width="800" />

## Step 2 : Add Standard Bluerint to the BDA Project

Next we will add a set of standard blueprints to the project. These blueprints are provided by AWS out-of-the-box. 

* click the “Edit” button on the project we just created
* Choose the ‘Custom Output’ tab, where we can see the Blueprints assigned to the project. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_2_-_idpdemo_project.png" width="800" />

*  Note the Project ID from the Project Details section (e.g., "c7ad285a4905" from the ARN "arn:aws:bedrock:XX-XXXX-X:XXXXXXXXXX:data-automation-project/c7ad285a4905"), you will need it while deploying the solution.
* “Select from enable checkbox” in the Document Splitter section.
* click the “Select from blueprint list” button. 
* Enter “US-Driver-License” into the search box, to find the “US-Driver-License” blueprint
* Select and click “Add blueprints”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_3_-_add_blueprint.png" width="800" />

Your project now will have one blueprint and looks like this. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_4_-_list_blueprints_1.png" width="800" />

* Save the changes to the project by clicking the "Save" button, then select "Create Blueprint" from the "Add Blueprint" dropdown menu.

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_5_-_create_blueprint.png" width="800" />


## Step 3 : Add Custom Blueprint to the BDA Project

We saw how to add sample blueprint to the BDA Project, now let's create a custom blueprint for the Child Support Enrollment Application form. You can add this blueprint using either the AWS Console or AWS CLI.

### Using AWS Console:

* Select the sample named “child-support-services-enrollment-form.pdf” for upload. Click the "Upload File" button.
* For an initial prompt, enter “This is an child support services enrollment form. Please extract all the keys and values from the form.”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_6_-_extraction_start.png" width="800" />


* Click the “Generate Blueprint” button. BDA will read the sample file, extract the keys and values, and create a new reusable Blueprint for Child Support Services Enrollment Forms. 
* Name the blueprint “child-support-services-enrollment-form-blueprint”


<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_7_-_extraction_end.png" width="800" />

* Click “Save and exit blueprint prompt”
* Click “Add to Project” and “Add to existing project”, add add this new blueprint to our project named “my-idpdemo-project”. 
* Click Generate result and review the extracted fields from the blueprint. BDA will identify and extract most of the key fields from the form based on the initial prompt, fields where data is not present in the document will appear blank. If you need to extract specific fields that weren't automatically detected, you can either:

    - Refine your initial prompt with more precise wording, or
    - Choose 'Manually create blueprint' to explicitly define which fields you want to extract.

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_8_-_extraction_details.png" width="800" />

Once your blueprint is created, you can enhance it with:
    - Custom Field Definitions
    - Data normalization rules
    - Transformation logic
    - Validation rules

### Using AWS CLI:

If you have created Blueprint using AWS Console, you can skip this Step. The blueprint schema for the Child Support Enrollment form with custom field defintions, Noramlization, Transformation and Validation configurations is available in [child-support-services-enrollment-form-blueprint.json](assets/documents/child-support-services-enrollment-form-blueprint.json).
 You can download the JSON and alternatively create a blueprint using AWS CLI:
```
aws bedrock-data-automation create-blueprint --blueprint-name "ChildSupportEnrollmentBluePrint" --type DOCUMENT --schema file://child-support-services-enrollment-form-blueprint.json
```
 

We now have a project with 2 blueprints. 

* Navigate to BDA, then “Projects”. Select the project named “my-idpdemo-project”. 
* Choose the ‘Custom Output’ tab, where we can see the Blueprints assigned to the project. You’ll now see our project has two blueprints. If you don’t see two blueprints, please go back and retrace your steps. For the next activity, we need to have all the blueprints associated with our project. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_9_-_list_blueprints_2.png" width="800" />


## Step 4 : Deployment
Once the Project with 2 blue prints are created you are ready for end to end deployment using AWS CDK. Check the Deployment Instruction [ReadMe.md](ReadMe.md)

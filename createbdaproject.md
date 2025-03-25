# Instructions to create Bedrock Data Automation Blueprint and Project Via the AWS Console

For this solution, we will be processing a PDF file which has 2 documents - 1) Child Support Services Enrollment Form 2) Driver License using Bedrock Data Automation (BDA). We will use BDA to identify each document, and then to extract the data we need for downstream processing

We will next create a project within BDA.

* Navigate to AWS Console
* Search for Bedrock in the "Services" search bar
* Once in the Bedrock console, click on the "Projects" menu under Data Automation.  
* Then click the “Create Project” button
* Name the project “my-idpdemo-project”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_1_-_BDA_Projects.png" width="800" />

Next we will add a set of standard blueprints to the project. These blueprints are provided by AWS out-of-the-box. 

* click the “Edit” button on the project we just created
* Choose the ‘Custom Output’ tab, where we can see the Blueprints assigned to the project. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_2_-_idpdemo_project.png" width="800" />

* “Select from enable checkbox” in the Document Splitter section.
* click the “Select from blueprint list” button. 
* Enter “US-Driver-License” into the search box, to find the “US-Driver-License” blueprint
* Select and click “Add blueprints”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_3_-_add_blueprint.png" width="800" />

Your project now will have one blueprint and looks like this. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_4_-_list_blueprints_1.png" width="800" />

We saw how to add sample blueprint to the BDA Project, now let’s custom blueprint. 

* Save the changes, to the project, click the “Save“ button and then ”Create Blueprint“

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_5_-_create_blueprint.png" width="800" />


* Select the sample named “child-support-services-enrollment-form.pdf” for upload. Click the "Upload File" button.
* For an initial prompt, enter “This is an child support services enrollment form. Please extract all the keys and values from the form.”

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_6_-_extraction_start.png" width="800" />


* Click the “Generate Blueprint” button. BDA will read the sample file, extract the keys and values, and create a new reusable Blueprint for future Homeowners Insurance Application forms. 
* Name the blueprint “child-support-services-enrollment-form”
* Click “Add to Project” and “Add to existing project”, add add this new blueprint to our project named “my-idpdemo-project”. 
* Click “Save and exit blueprint prompt”
* Examine the results from the blueprint. Note that BDA has read all the fields from the form. Depending on your initial prompt, review the resuls, you can tweak the wording of the initial prompt, or choose "Manually create blueprint" and specify each field you want to extract.

We now have a project with 2 blueprints. 

* Navigate to BDA, then “Projects”. Select the project named “my-idpdemo-project”. 
* Choose the ‘Custom Output’ tab, where we can see the Blueprints assigned to the project. You’ll now see our project has two blueprints. If you don’t see six blueprints, please go back and retrace your steps. For the next activity, we need to have all the blueprints associated with our project. 

<img src="../../blob/main/assets/screenshots/AWS_Console_Screenshot_8_-_list_blueprints_2.png" width="800" />


```bash
# to be run from the deployment/ folder
python ../source/lending_flow/activate_document_splitting.py my-lending-project
```

This should result in the following output, which has the document splitter now enabled.

```bash
(.venv) ~/projects/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/deployment python ../source/lending_flow/activate_document_splitting.py my-idpdemo-project
Get project list and find matching project for my-lending-project
Activating document splitting for project: my-lending-project, arn:aws:bedrock:us-west-2:XXXXXXXXXXXX:data-automation-project/XXXXXXX

Updated override configuration of project:
{
  "document": {
    "splitter": {
      "state": "ENABLED"
    }
  }
}


```
# Integrations Platform Engineer - Take-Home Assessment

## Overview

This assessment is designed to evaluate your skills in CI/CD automation, infrastructure understanding, and basic programming knowledge. The assessment consists of two parts and should take approximately 1-2 hours total to complete.

---

# CI/CD Pipeline for Integration Validation

## 🍫 The Scenario: Wonka's Chocolate Factory Integration Platform

### Background Story
You've been asked to help out as a new Data Platform Engineer at a company called Wonka's Chocolate. Their factory has been modernizing its operations and relies heavily on XML validation to coordinate everything from recipe distribution to quality control across their production facilities.

However, there's been chaos in the integration pipeline. One of the employees accidentally deployed a faulty chocolate mixing process last week that caused the candy systems to go haywire. The CEO has declared that **no integration process can be deployed without proper automated validation**.

### Your Task

Create a GitHub Actions workflow that analyzes the company's new process XMLs and validates they meet the company's new production standards.

### Requirements

#### 1. GitHub Actions Workflow (Primary Focus)
Create a `.github/workflows/xml-validation.yml` file that:

- **Triggers on**: Pull requests affecting XML files in a `xml-processes/` directory

- **Validates the following Factory Safety Standards**:

  - ✅ **Process must have quality control error handling**: Verify the XML contains at least one shape with `shapetype="returndocuments"` that has a label containing "Error" (case-insensitive). *This ensures that if something goes wrong during chocolate production, the process can safely handle failures.*

  - ✅ **No deprecated candy-making components**: Ensure the XML does not contain any shapes with `componentId` attribute matching the following blocklist of dangerous legacy components:

    - `ab12cd34-5678-90ef-ghij-klmnopqrstuv` (Legacy Taffy Puller v1.0 - known to create sentient taffy)

    - `ff00aa11-2233-4455-6677-889900bbccdd` (Chocolate Tempering Module v2.1 - random chance of creating exploding chocolate bars)

    - `151411ac-6724-21ae-giz-00000000azz1a` (Wonka Bar Wrapper v0.9 - privilege escalation vulnerability grants unauthorized factory tour access)
    
    - `12345678-9abc-def0-1234-56789abcdef0` (Sugar Rush Accelerator v3.2 - banned after the Great Candy Cane Incident of 2020)

- **Outputs**: Clear success/failure messages with specific details about what passed or failed

- **Bonus**: Add a step that posts validation results as a PR comment

#### 2. Implementation Requirements

- Use appropriate GitHub Actions marketplace actions where beneficial

- Include proper error handling and meaningful exit codes

- Structure the workflow for maintainability (consider reusable actions/steps)

- Add basic security considerations (e.g., appropriate permissions)


### Deliverables - Part 1
1. **GitHub Actions workflow file** (`.github/workflows/xml-validation.yml`)
2. **Any supporting scripts** (if you choose to write custom validation logic)
3. **README.md** with (2-3 paragraphs) of your approach, any assumptions made, and potential improvements

### Evaluation Criteria - Part 1
We'll assess your submission on:

- **Functionality**: Does the workflow correctly identify the required conditions?

- **Code Quality**: Is the solution well-structured and maintainable?

- **Documentation**: Are your choices and approach clearly explained?

- **Practical Considerations**: Have you thought about real-world usage, security, and maintenance?

### Questions for Discussion - Part 1
Be prepared to discuss:

- Trade-offs between custom scripts vs. marketplace actions

- Strategies for handling secrets in CI/CD pipelines

- How you would monitor and troubleshoot workflow failures?

- Approaches for testing GitHub Actions workflows locally

- What strategies would you use to make the validation rules easily maintainable and extensible?

### Getting Started - Part 1
1. Create a new GitHub Repository and include this folder
2. Implement your XML validation workflow
3. Test your workflow using the provided example XMLs:
   - `example_file_valid.xml` - Valid process with proper error handling
   - `example_with_deprecated_component.xml` - Contains a deprecated componentId (should fail validation)
   - `example_missing_error_handling.xml` - Missing required error handling (should fail validation)

### Notes - Part 1

- You don't need to set up a complete repository structure - focus on the workflow and validation logic
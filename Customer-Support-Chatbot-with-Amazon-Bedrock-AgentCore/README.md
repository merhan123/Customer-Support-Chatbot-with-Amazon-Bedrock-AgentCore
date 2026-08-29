# Customer Support Chatbot with Amazon Bedrock AgentCore

## Architecture

This project implements a customer support chatbot with three prompt-controlled routes:

1. **Bug reports** — collect `description`, `stepsToReproduce`, and `environment`, then call `bugreports___create_bug_report` through the AgentCore Gateway and return the generated ticket ID.
2. **Platform questions** — answer only from the FAQ embedded through the `{{FAQ}}` placeholder.
3. **Other requests** — politely redirect to human support at `1-800-555-0199 (Mon-Fri)`.

The current project version uses the **Amazon Bedrock AgentCore managed harness**. Classification and routing are therefore implemented inside `system_prompt.txt`, rather than with separate Bedrock Flow classifier/Condition nodes.

## Prompt Design

The system prompt:
- forces exactly one route per customer message;
- prevents the bug-report tool from being called until all three required fields are available;
- asks for missing bug information one item at a time;
- grounds platform answers only in the embedded FAQ;
- redirects FAQ gaps and out-of-scope requests to human support;
- includes basic prompt-injection resistance and anti-fabrication rules.

## Automated Tests

`harness-tests.json` covers:
- FAQ questions;
- incomplete and complete bug reports;
- unsupported requests;
- ambiguous inputs;
- mixed-intent inputs;
- prompt-injection attempts.

Each automated test is intended to run in a fresh AgentCore session.

## Manual Validation Checklist

After the AgentCore Gateway and harness are available:

1. Run `python3 chat.py`.
2. Test a multi-turn bug report.
3. Capture the line:
   `[tool call] bugreports___create_bug_report`
4. Confirm the assistant returns the real `ticketId`.
5. Verify the stored record:
   `aws dynamodb scan --table-name bug-report-tool-stack-bug-reports --region us-east-1`
6. Test one FAQ-covered question.
7. Test one FAQ-uncovered question.
8. Test one unrelated/other request.

## Evaluation

Run:

```bash
python3 generate-eval-dataset.py --tests-json harness-tests.json
```

This should create `output_eval_dataset.jsonl`.

Then upload the JSONL file to the evaluation S3 bucket and create a Bedrock Evaluation job using LLM-as-a-judge with the built-in Correctness metric.

## Evaluation Observations

**Fill this section after the real evaluation run.**

Recommended observations to record:
- overall correctness score;
- whether all three routes were classified correctly;
- any bug-report cases that called the tool too early;
- whether FAQ responses stayed grounded;
- whether unsupported requests were handed off correctly;
- any prompt-injection or ambiguous cases that required prompt refinement.

## Evidence

Place real runtime screenshots in the `evidence/` folder:

- `01_bug_chat.png`
- `02_bug_tool_call.png`
- `03_dynamodb_ticket.png`
- `04_faq_covered.png`
- `05_faq_uncovered.png`
- `06_other_request.png`
- `07_evaluation_results.png`

Do not fabricate these screenshots; they should come from the actual AWS run.

## Environment Limitation / AgentCore IAM Blocker

The application design, system prompt, and automated test suite were completed. However, the provided Udacity/VocLabs AWS role does not grant permission to create an Amazon Bedrock AgentCore Gateway.

The failure was reproduced in both the provided `setup_gateway.py` script and the AWS Management Console. AWS returned:

```text
User: arn:aws:sts::779603594409:assumed-role/voclabs/user5296755=2d0c6edc-44d7-11ea-a45c-f7d5bc8e1851 is not authorized to perform: bedrock-agentcore:CreateGateway on resource: arn:aws:bedrock-agentcore:us-east-1:779603594409:gateway/* because no identity-based policy allows the bedrock-agentcore:CreateGateway action
```

Because Gateway creation is a prerequisite for `agentcore_config.json`, harness creation, and end-to-end tool invocation, the following runtime artifacts could not be produced in this lab session:

- a live `bugreports___create_bug_report` tool-call transcript;
- a DynamoDB ticket created through the chatbot/harness;
- `output_eval_dataset.jsonl` generated from live harness responses;
- a completed Bedrock Evaluations job/results screenshot.

These artifacts have intentionally **not** been fabricated. The included `system_prompt.txt` and `harness-tests.json` are ready to run once the lab role is granted `bedrock-agentcore:CreateGateway` and the other AgentCore permissions required by the supplied project scripts.

### Reproduction

```bash
python3 setup_gateway.py
```

Result: `AccessDeniedException` for `bedrock-agentcore:CreateGateway`.

The same authorization failure occurs when attempting to create the Gateway manually in the AWS Console.

### Required resolution

The Udacity/VocLabs lab role must be updated by the environment administrator to allow the AgentCore Gateway operations required by the project. After that, the intended completion sequence is:

```bash
python3 setup_gateway.py
python3 create_harness.py
python3 chat.py
python3 generate-eval-dataset.py --tests-json harness-tests.json
```

The resulting DynamoDB ticket, JSONL evaluation dataset, and Bedrock Evaluation results can then be added as final runtime evidence.

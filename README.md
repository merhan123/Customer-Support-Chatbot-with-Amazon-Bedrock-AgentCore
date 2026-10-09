# Customer Support Chatbot with Amazon Bedrock AgentCore

A customer support chatbot built with Amazon Bedrock AgentCore and Amazon Nova Pro. It collects bug reports, answers platform questions from an FAQ, and directs other requests to human support.

## Architecture

```text
Customer
  -> AgentCore Harness (MyHarness)
  -> System prompt routing
     -> BUG REPORT -> AgentCore Gateway (supportgateway) -> Lambda (create_bug_report.py) -> DynamoDB
     -> PLATFORM QUESTION -> FAQ-only answer
     -> OTHER REQUEST -> Human support phone line
```

The deployed model is `us.amazon.nova-pro-v1:0`.

## Three Routes

1. `BUG REPORT`
   Collect `description`, `stepsToReproduce`, and `environment`. The harness must ask for one missing field at a time and call `create_bug_report` only after all three are present.
2. `PLATFORM QUESTION`
   Answer only from `online_shop_faq.md`, which is embedded directly into [`app/MyHarness/system-prompt.md`](app/MyHarness/system-prompt.md).
3. `OTHER REQUEST`
   Politely redirect the customer to `1-800-555-0199 (Mon-Fri)`.

## Repository Layout

```text
.
├── README.md
├── LICENSE.md
├── .gitignore
├── app/
│   └── MyHarness/
│       ├── harness.json
│       └── system-prompt.md
├── agentcore/
│   ├── agentcore.json
│   ├── aws-targets.json
│   └── cdk/
├── infrastructure/
│   ├── cloudformation-tool.yaml
│   └── cloudformation-testing.yaml
├── bug_report_tools.json
├── create_bug_report.py
├── chat_workaround.py
├── generate-eval-dataset-workaround.py
├── harness-tests.json
├── online_shop_faq.md
└── requirements.txt
```

The project uses the declarative AgentCore CLI workflow.

## Current AgentCore CLI Workflow

For a fresh project, the current CLI flow is:

```bash
agentcore create --name customersupportchatbot --model-provider Bedrock
agentcore add gateway --name supportgateway
agentcore add gateway-target \
  --name bugreports \
  --type lambda-function-arn \
  --lambda-arn arn:aws:lambda:us-east-1:779603594409:function:bug-report-tool-stack-create-bug-report \
  --tool-schema-file bug_report_tools.json \
  --gateway supportgateway
agentcore add harness --name MyHarness
agentcore add tool --harness MyHarness --type agentcore_gateway --name supportgateway
agentcore validate
agentcore deploy
agentcore status
```

This repository already contains the equivalent declarative configuration in [`agentcore/agentcore.json`](agentcore/agentcore.json) and [`app/MyHarness/harness.json`](app/MyHarness/harness.json).

## Deployed Resources

- Harness: `MyHarness`
- Model: `us.amazon.nova-pro-v1:0`
- Gateway: `supportgateway`
- Gateway target: `bugreports`
- Lambda: `bug-report-tool-stack-create-bug-report`
- DynamoDB table: `bug-report-tool-stack-bug-reports`

## Runtime Limitation

As of August 30, 2026, `agentcore deploy` has succeeded for this project, but the Udacity/VocLabs role still blocks direct harness invocation. In this lab account, `agentcore invoke` fails with HTTP 403 because the role does not allow `bedrock-agentcore:InvokeHarness`.

That limitation affects runtime verification only. The repository keeps the real deployed configuration and does not claim successful `InvokeHarness` results that were not observed.

## Testing Workaround

Because `InvokeHarness` is denied, local testing uses:

- `chat_workaround.py`
  Sends prompts to Amazon Bedrock Converse with `us.amazon.nova-pro-v1:0` and invokes the Lambda directly when the model requests `create_bug_report`.
- `generate-eval-dataset-workaround.py`
  Runs the prompts in `harness-tests.json` through the same workaround path and writes `output_eval_dataset.jsonl`.

Example commands:

```bash
python3 chat_workaround.py
python3 generate-eval-dataset-workaround.py --tests-json harness-tests.json
```

## Test Assets

- [`harness-tests.json`](harness-tests.json)
  Covers incomplete bug reports, complete bug reports, FAQ-covered questions, FAQ gaps, unsupported requests, ambiguous mixed intent, and prompt injection attempts.

## Evaluation

Generate a fresh dataset with `generate-eval-dataset-workaround.py` from an environment with Bedrock access. The generated `output_eval_dataset.jsonl` is excluded from version control. Review the output for successful responses before using it with Amazon Bedrock Evaluations.

## Validation

```bash
agentcore validate
python3 -m py_compile chat_workaround.py
python3 -m py_compile generate-eval-dataset-workaround.py
python3 -m py_compile create_bug_report.py
```

Full runtime verification requires permission to invoke the deployed harness.

## Offline unit tests

Run `python3 -m unittest discover -s tests -v` from the repository root.
The tests mock AWS and check Lambda input handling and evaluation-tool validation.
They do not create tickets or invoke Bedrock. Live integration needs configured AWS access.

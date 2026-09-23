#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import boto3
from chat_workaround import validate_bug_args

REGION_DEFAULT = "us-east-1"
MODEL_ID_DEFAULT = "us.amazon.nova-pro-v1:0"
SYSTEM_PROMPT_PATH_DEFAULT = str(Path(__file__).resolve().parent / "app/MyHarness/system-prompt.md")
LAMBDA_FUNCTION_DEFAULT = "bug-report-tool-stack-create-bug-report"

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "create_bug_report",
                "description": (
                    "Create a bug ticket only after the customer has supplied "
                    "a concrete bug description, concrete reproduction steps, "
                    "and concrete environment details."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "What is broken, in the customer's own words."
                            },
                            "stepsToReproduce": {
                                "type": "string",
                                "description": "Concrete steps that reproduce the issue."
                            },
                            "environment": {
                                "type": "string",
                                "description": "Concrete browser, OS, device, or other environment details."
                            }
                        },
                        "required": [
                            "description",
                            "stepsToReproduce",
                            "environment"
                        ]
                    }
                }
            }
        }
    ]
}


def visible_text(message: Dict[str, Any]) -> str:
    """Return user-visible text and hide model <thinking> passages."""
    parts: List[str] = []

    for block in message.get("content", []):
        text = block.get("text")
        if not text:
            continue

        text = re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.S)

        if text.strip():
            parts.append(text.strip())

    return "\n".join(parts).strip()


def invoke_lambda(lambda_client, function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Use the same validation as interactive chat before writing a ticket."""
    valid, error = validate_bug_args(args)
    if not valid:
        return {"error": error}
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(args).encode("utf-8"),
    )

    raw = response["Payload"].read()

    if response.get("FunctionError"):
        raise RuntimeError(raw.decode("utf-8", errors="replace"))

    return json.loads(raw.decode("utf-8"))


def invoke_once(
    bedrock_client,
    lambda_client,
    model_id: str,
    system_prompt: str,
    lambda_function: str,
    prompt: str,
) -> str:
    """
    Run one fresh-session test.

    A test may trigger the bug-report tool if all three required bug fields
    are already present in the single prompt.
    """
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"text": prompt}],
        }
    ]

    for _ in range(8):
        response = bedrock_client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={
                "temperature": 0,
                "maxTokens": 1200,
            },
        )

        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        tool_uses = [
            block["toolUse"]
            for block in assistant_message.get("content", [])
            if "toolUse" in block
        ]

        if not tool_uses:
            return visible_text(assistant_message)

        tool_results = []

        for tool_use in tool_uses:
            if tool_use["name"] != "create_bug_report":
                result = {
                    "error": f"Unknown tool requested: {tool_use['name']}"
                }
            else:
                try:
                    result = invoke_lambda(
                        lambda_client,
                        lambda_function,
                        tool_use["input"],
                    )
                except Exception as exc:
                    result = {
                        "error": f"{type(exc).__name__}: {exc}"
                    }

            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": result}],
                        "status": "error" if "error" in result else "success",
                    }
                }
            )

        # Bedrock Converse expects tool results in the next user message.
        messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

    raise RuntimeError("Tool loop exceeded 8 iterations.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run customer-support tests directly through Amazon Bedrock Converse "
            "and emit Bedrock Evaluations JSONL. This is a workaround for lab "
            "accounts that can deploy AgentCore but cannot call InvokeHarness."
        )
    )
    parser.add_argument(
        "--tests-json",
        required=True,
        help="Path to harness-tests.json",
    )
    parser.add_argument(
        "--system-prompt",
        default=SYSTEM_PROMPT_PATH_DEFAULT,
        help="Path to the system prompt used by the harness.",
    )
    parser.add_argument(
        "--model-id",
        default=MODEL_ID_DEFAULT,
        help="Bedrock model ID.",
    )
    parser.add_argument(
        "--lambda-function",
        default=LAMBDA_FUNCTION_DEFAULT,
        help="Bug-report Lambda function name or ARN.",
    )
    parser.add_argument(
        "--model-identifier",
        default="my-support-chatbot",
        help="Value stored in modelResponses[0].modelIdentifier.",
    )
    parser.add_argument(
        "--out-jsonl",
        default="output_eval_dataset.jsonl",
        help="Output Bedrock Evaluations JSONL path.",
    )
    parser.add_argument(
        "--region",
        default=REGION_DEFAULT,
        help="AWS region.",
    )
    args = parser.parse_args()

    suite = json.loads(Path(args.tests_json).read_text(encoding="utf-8"))
    tests = suite["tests"]

    system_prompt_path = Path(args.system_prompt)
    if not system_prompt_path.exists():
        sys.exit(f"System prompt not found: {system_prompt_path}")

    system_prompt = system_prompt_path.read_text(encoding="utf-8")

    session = boto3.Session(region_name=args.region)
    bedrock_client = session.client("bedrock-runtime")
    lambda_client = session.client("lambda")

    out_path = Path(args.out_jsonl)
    n_ok = 0

    with out_path.open("w", encoding="utf-8") as f:
        for test in tests:
            test_id = test["id"]
            prompt = test["prompt"]
            reference = test.get("expected", "")

            try:
                response_text = invoke_once(
                    bedrock_client=bedrock_client,
                    lambda_client=lambda_client,
                    model_id=args.model_id,
                    system_prompt=system_prompt,
                    lambda_function=args.lambda_function,
                    prompt=prompt,
                )
                n_ok += 1
            except Exception as exc:
                response_text = (
                    f"[BEDROCK_ERROR] {type(exc).__name__}: {exc}"
                )

            record = {
                "prompt": prompt,
                "referenceResponse": reference,
                "modelResponses": [
                    {
                        "response": response_text,
                        "modelIdentifier": args.model_identifier,
                    }
                ],
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"{test_id}: wrote eval line", file=sys.stderr)

    print(
        f"\nWrote {len(tests)} JSONL lines to {out_path} "
        f"({n_ok} Bedrock calls succeeded).",
        file=sys.stderr,
    )


    return 0 if n_ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())

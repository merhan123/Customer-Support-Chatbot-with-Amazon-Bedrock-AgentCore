#!/usr/bin/env python3
"""
Hardened local testing workaround for the AgentCore chatbot project.

Uses:
- Amazon Bedrock Converse API + Amazon Nova Pro
- In-memory multi-turn conversation state
- Direct Lambda invocation for create_bug_report
- Validation to prevent placeholder/fabricated bug tickets
"""

import json
import re
import sys
import uuid
from pathlib import Path

import boto3

REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
LAMBDA_FUNCTION = "bug-report-tool-stack-create-bug-report"
SYSTEM_PROMPT_PATH = Path("app/MyHarness/system-prompt.md")

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "create_bug_report",
                "description": (
                    "Create a bug ticket only after the customer has supplied "
                    "a concrete bug description, concrete reproduction steps, "
                    "and concrete environment details. Never use field names, "
                    "examples, placeholders, or guessed values."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Concrete description of what is broken."
                            },
                            "stepsToReproduce": {
                                "type": "string",
                                "description": "Concrete steps the customer actually performed."
                            },
                            "environment": {
                                "type": "string",
                                "description": "Concrete browser/OS/device details supplied by the customer."
                            }
                        },
                        "required": ["description", "stepsToReproduce", "environment"]
                    }
                }
            }
        }
    ]
}

PLACEHOLDER_VALUES = {
    "description",
    "steps",
    "steps to reproduce",
    "stepstoreproduce",
    "environment",
    "browser",
    "os",
    "device",
    "unknown",
    "n/a",
    "na",
    "none",
    "placeholder",
    "example",
}


def load_system_prompt():
    if not SYSTEM_PROMPT_PATH.exists():
        sys.exit(f"Missing {SYSTEM_PROMPT_PATH}")
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def looks_like_real_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = " ".join(value.strip().split())
    if len(cleaned) < 4:
        return False
    if cleaned.lower() in PLACEHOLDER_VALUES:
        return False
    # Reject function-signature-like placeholders.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned):
        return False
    return True


def validate_bug_args(args: dict):
    required = ["description", "stepsToReproduce", "environment"]
    missing_or_invalid = [
        key for key in required if not looks_like_real_value(args.get(key))
    ]
    if missing_or_invalid:
        return False, (
            "Tool call rejected because these fields do not contain concrete "
            "customer-provided values: " + ", ".join(missing_or_invalid)
        )
    return True, None


def invoke_lambda(lambda_client, args):
    ok, error = validate_bug_args(args)
    if not ok:
        print(f"\n[tool call blocked] {error}")
        return {"error": error}

    print(
        "\n[tool call] bugreports___create_bug_report "
        + json.dumps(args, ensure_ascii=False)
    )

    response = lambda_client.invoke(
        FunctionName=LAMBDA_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(args).encode("utf-8"),
    )
    raw = response["Payload"].read()

    if response.get("FunctionError"):
        raise RuntimeError(raw.decode("utf-8", errors="replace"))

    result = json.loads(raw.decode("utf-8"))
    print("[tool result]", json.dumps(result, ensure_ascii=False))
    return result


def visible_text(message):
    parts = []
    for block in message.get("content", []):
        text = block.get("text")
        if not text:
            continue
        # Hide model-internal <thinking> blocks from the user-facing transcript.
        text = re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.S)
        if text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def run_turn(brt, lambda_client, system_prompt, messages, user_text):
    messages.append({"role": "user", "content": [{"text": user_text}]})

    for _ in range(8):
        response = brt.converse(
            modelId=MODEL_ID,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"temperature": 0, "maxTokens": 1200},
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
                result = {"error": f"Unknown tool: {tool_use['name']}"}
            else:
                result = invoke_lambda(lambda_client, tool_use["input"])

            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": result}],
                        "status": "error" if "error" in result else "success",
                    }
                }
            )

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Tool loop exceeded 8 iterations")


def main():
    print("Customer Support Chatbot — hardened local test")
    print(f"Model: {MODEL_ID}")
    print("Type 'exit' to quit.\n")

    system_prompt = load_system_prompt()
    brt = boto3.client("bedrock-runtime", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)

    messages = []
    print(f"Session: {uuid.uuid4()}\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            break

        try:
            answer = run_turn(
                brt, lambda_client, system_prompt, messages, user_text
            )
            print(f"\nAssistant: {answer}\n")
        except Exception as exc:
            print(f"\nERROR: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()

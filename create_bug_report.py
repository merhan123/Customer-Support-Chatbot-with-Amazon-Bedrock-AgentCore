import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
REQUIRED_FIELDS = ("description", "stepsToReproduce", "environment")


def _tool_name(context):
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None) or {}
    name = custom.get("bedrockAgentCoreToolName", "")
    if "___" in name:
        return name.split("___")[-1]
    return name


def _normalize_payload(event):
    if not isinstance(event, dict):
        return None

    if "parameters" in event and "messageVersion" in event:
        params = event.get("parameters")
        if not isinstance(params, list):
            return None
        return {
            param.get("name"): param.get("value")
            for param in params
            if isinstance(param, dict) and isinstance(param.get("name"), str)
        }

    return event


def _clean_payload(payload):
    return {field: payload[field].strip() if isinstance(payload.get(field), str) else "" for field in REQUIRED_FIELDS}


def lambda_handler(event, context):
    tool_name = _tool_name(context)
    if tool_name and tool_name != "create_bug_report":
        LOGGER.warning("Unsupported tool requested: %s", tool_name)
        return {"error": f"unsupported tool: {tool_name}"}

    payload = _normalize_payload(event)
    if payload is None:
        LOGGER.warning("Unexpected event type: %s", type(event).__name__)
        return {"error": "unexpected event shape"}

    LOGGER.info("Received create_bug_report request with keys: %s", sorted(str(key) for key in payload))
    body = _clean_payload(payload)

    missing = [field for field, value in body.items() if not value]
    if missing:
        LOGGER.info("Rejecting incomplete bug report; missing fields: %s", ",".join(missing))
        return {
            "error": (
                "missing required field(s): "
                + ", ".join(missing)
                + ". Ask the customer for them before filing the ticket."
            )
        }

    ticket_id = str(uuid.uuid4())
    item = {
        "ticketId": ticket_id,
        "description": body["description"],
        "stepsToReproduce": body["stepsToReproduce"],
        "environment": body["environment"],
        "status": "OPEN",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    try:
        TABLE.put_item(Item=item)
    except Exception:
        LOGGER.exception("Failed to store bug report in DynamoDB.")
        return {"error": "internal error while creating bug report"}

    LOGGER.info("Created bug report ticketId=%s status=OPEN", ticket_id)
    return {"ticketId": ticket_id, "status": "OPEN"}

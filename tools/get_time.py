# tools/get_time.py
#
# Ported from hello_agent.py's get_time, adapted to the Tool/ToolResult
# contract in agent/runtime.py: the handler returns a ToolResult instead
# of a bare string, so the runtime can tell success from failure without
# parsing text.
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.runtime import Tool, ToolResult


def _handler(arguments: dict) -> ToolResult:
    tz_name = arguments.get("timezone", "UTC")
    try:
        tz = timezone.utc if tz_name == "UTC" else ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ToolResult(ok=False, error_code="unknown_timezone")
    return ToolResult(ok=True, data=datetime.now(tz).isoformat())


get_time = Tool(
    name="get_time",
    description="Return the current time as an ISO-8601 timestamp in the given IANA timezone.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone name, e.g. 'Europe/Paris'. Defaults to UTC.",
            }
        },
        "required": [],
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=False,
)

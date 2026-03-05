import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


PROTOCOL_VERSION = "2025-11-25"

SERVER_INFO = {
    "name": "lambda-mcp-server",
    "version": "0.4.0",
}

TOOLS = [
    {
        "name": "echo",
        "description": "Return the input text unchanged.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back.",
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "utc_now",
        "description": "Return the current UTC timestamp.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "add_numbers",
        "description": "Add two numbers and return the total.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First value."},
                "b": {"type": "number", "description": "Second value."},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    },
    {
        "name": "text_stats",
        "description": "Return character, word, and line counts for input text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to analyze.",
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "weather",
        "description": "Fetch the current weather for a city using Open-Meteo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, for example 'Boston' or 'Nashville'.",
                }
            },
            "required": ["city"],
            "additionalProperties": False,
        },
    },
]


def _response(
    status_code: int,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response_headers = {"Content-Type": "application/json"}
    if headers:
        response_headers.update(headers)
    return {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(body),
    }


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_result(text: str) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ]
    }


def _extract_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        raise ValueError("Request body is required.")

    if event.get("isBase64Encoded"):
        raise ValueError("Base64-encoded request bodies are not supported.")

    if isinstance(raw_body, dict):
        return raw_body

    return json.loads(raw_body)


def _handle_initialize(request_id: Any) -> dict[str, Any]:
    return _json_rpc_result(
        request_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": {
                "experimental": {},
                "prompts": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "tools": {"listChanged": False},
            },
        },
    )


def _handle_tools_list(request_id: Any) -> dict[str, Any]:
    return _json_rpc_result(request_id, {"tools": TOOLS})


def _handle_prompts_list(request_id: Any) -> dict[str, Any]:
    return _json_rpc_result(request_id, {"prompts": []})


def _handle_resources_list(request_id: Any) -> dict[str, Any]:
    return _json_rpc_result(request_id, {"resources": []})


def _handle_resource_templates_list(request_id: Any) -> dict[str, Any]:
    return _json_rpc_result(request_id, {"resourceTemplates": []})


def _require_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise ValueError(f"The '{key}' argument must be a string.")
    return value


def _require_number(arguments: dict[str, Any], key: str) -> float:
    value = arguments.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"The '{key}' argument must be a number.")
    return float(value)


def _call_echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(_require_string(arguments, "text"))


def _call_utc_now(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments not in ({}, None):
        raise ValueError("The 'utc_now' tool does not accept arguments.")
    return _tool_result(datetime.now(timezone.utc).isoformat())


def _call_add_numbers(arguments: dict[str, Any]) -> dict[str, Any]:
    total = _require_number(arguments, "a") + _require_number(arguments, "b")
    return _tool_result(str(total))


def _call_text_stats(arguments: dict[str, Any]) -> dict[str, Any]:
    text = _require_string(arguments, "text")
    stats = {
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()) or 1,
    }
    return _tool_result(json.dumps(stats))


def _fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urlencode(params)
    request_url = f"{url}?{query}"
    with urlopen(request_url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _call_weather(arguments: dict[str, Any]) -> dict[str, Any]:
    city = _require_string(arguments, "city")

    geocode = _fetch_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": city, "count": 1, "language": "en", "format": "json"},
    )
    results = geocode.get("results") or []
    if not results:
        raise ValueError(f"No weather location match found for '{city}'.")

    location = results[0]
    forecast = _fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,apparent_temperature,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        },
    )
    current = forecast.get("current")
    if not current:
        raise ValueError("Weather data was unavailable from Open-Meteo.")

    place = ", ".join(
        part
        for part in [
            location.get("name"),
            location.get("admin1"),
            location.get("country"),
        ]
        if part
    )
    weather_summary = {
        "location": place,
        "temperature_f": current.get("temperature_2m"),
        "feels_like_f": current.get("apparent_temperature"),
        "wind_mph": current.get("wind_speed_10m"),
        "observed_at": current.get("time"),
    }
    return _tool_result(json.dumps(weather_summary))


TOOL_HANDLERS = {
    "echo": _call_echo,
    "utc_now": _call_utc_now,
    "add_numbers": _call_add_numbers,
    "text_stats": _call_text_stats,
    "weather": _call_weather,
}


def _handle_tools_call(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return _json_rpc_error(
            request_id,
            -32601,
            "Tool not found",
            {"tool": tool_name},
        )

    try:
        return _json_rpc_result(request_id, handler(arguments))
    except ValueError as exc:
        return _json_rpc_error(
            request_id,
            -32602,
            "Invalid params",
            {"reason": str(exc)},
        )
    except (HTTPError, URLError, TimeoutError) as exc:
        return _json_rpc_error(
            request_id,
            -32000,
            "Tool execution failed",
            {"reason": f"Weather service request failed: {exc}"},
        )


def lambda_handler(event, context):
    method = (
        ((event.get("requestContext") or {}).get("http") or {}).get("method")
        or event.get("httpMethod")
        or "POST"
    )

    if method.upper() == "GET":
        return _response(
            405,
            _json_rpc_error(
                None,
                -32600,
                "Method not allowed",
                {"reason": "This endpoint supports POST for JSON-RPC. SSE over GET is not implemented."},
            ),
            {"Allow": "GET, POST"},
        )

    if method.upper() != "POST":
        return _response(
            405,
            _json_rpc_error(None, -32600, "Invalid Request", {"reason": "Use POST."}),
            {"Allow": "GET, POST"},
        )

    try:
        request = _extract_body(event)
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(
            400,
            _json_rpc_error(None, -32700, "Parse error", {"reason": str(exc)}),
        )

    request_id = request.get("id")
    rpc_method = request.get("method")
    params = request.get("params", {})

    if request.get("jsonrpc") != "2.0":
        return _response(
            400,
            _json_rpc_error(request_id, -32600, "Invalid Request"),
        )

    if rpc_method == "initialize":
        return _response(200, _handle_initialize(request_id))

    if rpc_method == "notifications/initialized":
        return _response(202, {})

    if rpc_method == "notifications/cancelled":
        return _response(202, {})

    if rpc_method == "tools/list":
        return _response(200, _handle_tools_list(request_id))

    if rpc_method == "prompts/list":
        return _response(200, _handle_prompts_list(request_id))

    if rpc_method == "resources/list":
        return _response(200, _handle_resources_list(request_id))

    if rpc_method == "resources/templates/list":
        return _response(200, _handle_resource_templates_list(request_id))

    if rpc_method == "tools/call":
        if not isinstance(params, dict):
            return _response(
                400,
                _json_rpc_error(
                    request_id,
                    -32602,
                    "Invalid params",
                    {"reason": "Expected params to be an object."},
                ),
            )
        return _response(200, _handle_tools_call(request_id, params))

    return _response(
        404,
        _json_rpc_error(
            request_id,
            -32601,
            "Method not found",
            {"method": rpc_method},
        ),
    )

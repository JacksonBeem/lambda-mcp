Flow diagrams for class demo:

- FLOW_DIAGRAM.md (runtime flow, SAM deploy flow, sequence diagram)

# Lambda MCP Server — Comprehensive Project Documentation

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Architecture](#3-architecture)
4. [Infrastructure Configuration: `template.yaml`](#4-infrastructure-configuration-templateyaml)
5. [Deployment Configuration: `samconfig.toml`](#5-deployment-configuration-samconfigtoml)
6. [Build Artifacts: `packaged.yaml` and `build.toml`](#6-build-artifacts-packagedyaml-and-buildtoml)
7. [Application Code: `lambda_function.py`](#7-application-code-lambda_functionpy)
8. [MCP Protocol Implementation](#8-mcp-protocol-implementation)
9. [Tool Reference](#9-tool-reference)
10. [Authentication and Security](#10-authentication-and-security)
11. [API Gateway: How It Is Configured](#11-api-gateway-how-it-is-configured)
12. [Deployment Procedure](#12-deployment-procedure)
13. [Functional Verification](#13-functional-verification)
14. [Change Workflow](#14-change-workflow)
15. [Troubleshooting](#15-troubleshooting)
16. [Decommission](#16-decommission)
17. [Command Reference](#17-command-reference)

---

## 1. Project Overview

This project deploys a **Model Context Protocol (MCP) server** as an AWS Lambda function exposed over HTTPS via API Gateway HTTP API. The server implements the JSON-RPC 2.0 wire format required by MCP-compatible clients (such as Claude).

There are two related Lambda deployments in this workspace:

| Directory | Stack Name | Tools | Auth |
|---|---|---|---|
| `lambda-mcp-1` | `lambda-mcp-server` | echo, utc_now, add_numbers, text_stats, weather | Bearer token |
| `lambda-mcp-1-tool` | `lambda-mcp-server-1-tool` | weather only | None |

The primary production deployment is `lambda-mcp-1`, which includes full bearer token authentication and five MCP tools. The `lambda-mcp-1-tool` directory is a simplified variant used for isolated tool testing.

**MCP Protocol Version:** `2024-11-05` (main), `2025-11-25` (tool variant)

**Public endpoint pattern:**
```
https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp
```

---

## 2. Repository Structure

```
lambda-mcp-1/
  lambda_function.py          # Application runtime (main, 5 tools + auth)
  PROJECT_DOCUMENTATION.md    # This file
  .deploy_build/
    lambda_function.py        # Copied source used during build packaging
    urllib3/                  # Bundled dependency
    idna/                     # Bundled dependency (urllib3 transitive dep)

lambda-mcp-1-tool/
  lambda_function.py          # Application runtime (weather tool only, no auth)
  template.yaml               # SAM infrastructure definition (source of truth)
  samconfig.toml              # SAM CLI deployment parameters
  packaged.yaml               # Generated post-packaging template (S3 CodeUri)
  requirements.txt            # Python dependencies (empty for main, requests for tool)
  .aws-sam/
    build.toml                # Auto-generated SAM build index
    build/
      template.yaml           # Transformed template used by CloudFormation
      LambdaMcpFunction/
        lambda_function.py    # Build-stage copy of function code
        samconfig.toml        # Copied config
        requirements.txt      # Copied requirements
        packaged.yaml         # Copied packaged template
```

---

## 3. Architecture

```
MCP Client (e.g., Claude)
        |
        | HTTPS POST /prod/mcp
        | Authorization: Bearer <token>
        | Content-Type: application/json
        | Body: JSON-RPC 2.0 payload
        v
+----------------------------+
|  API Gateway HTTP API      |
|  Stage: prod               |
|  Route: POST /mcp          |
|  Route: GET  /mcp          |
|  CORS: POST allowed        |
+----------------------------+
        |
        | Lambda Proxy Integration
        | (full event + context forwarded)
        v
+----------------------------+
|  AWS Lambda Function       |
|  Runtime: Python 3.12      |
|  Memory:  256 MB           |
|  Timeout: 15 s             |
|  Arch:    x86_64           |
+----------------------------+
        |
        | Outbound HTTPS (weather tool only)
        v
+----------------------------+
|  Open-Meteo API            |
|  geocoding-api.open-meteo  |
|  api.open-meteo.com        |
+----------------------------+
```

**Request flow:**

1. Client sends `POST /prod/mcp` with a JSON-RPC 2.0 body.
2. API Gateway receives the request, applies CORS headers, and forwards the full event to Lambda via proxy integration.
3. Lambda authenticates the bearer token.
4. Lambda parses the JSON-RPC method and dispatches to the appropriate handler.
5. The handler returns a JSON-RPC result or error, wrapped in an API Gateway proxy response (`statusCode`, `headers`, `body`).
6. API Gateway returns the HTTP response to the client.

---

## 4. Infrastructure Configuration: `template.yaml`

`template.yaml` is the **AWS SAM infrastructure-as-code** source file. SAM (Serverless Application Model) extends CloudFormation with higher-level resource types for Lambda and API Gateway.

### 4.1 Template Header

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Transform: AWS::Serverless-2016-10-31
```

- `AWSTemplateFormatVersion` — declares this is a CloudFormation template.
- `Transform: AWS::Serverless-2016-10-31` — instructs CloudFormation to expand SAM shorthand (`AWS::Serverless::*`) into native CloudFormation resources before deployment.

### 4.2 Global Function Defaults

```yaml
Globals:
  Function:
    Runtime: python3.12
    Timeout: 15
    MemorySize: 256
    Architectures:
      - x86_64
    Environment:
      Variables:
        PYTHONUNBUFFERED: "1"
```

All Lambda functions defined in the template inherit these defaults unless a resource-level override is specified:

| Property | Value | Effect |
|---|---|---|
| `Runtime` | `python3.12` | Uses CPython 3.12 managed runtime |
| `Timeout` | `15` seconds | Lambda is hard-killed after 15 s |
| `MemorySize` | `256` MB | Allocated RAM; also scales CPU proportionally |
| `Architectures` | `x86_64` | 64-bit Intel/AMD; use `arm64` for Graviton2 |
| `PYTHONUNBUFFERED` | `"1"` | Forces Python stdout/stderr to flush immediately to CloudWatch Logs |

### 4.3 API Gateway Resource: `McpHttpApi`

```yaml
Resources:
  McpHttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: prod
      CorsConfiguration:
        AllowMethods:
          - POST
        AllowHeaders:
          - authorization
          - content-type
        AllowOrigins:
          - "*"
```

`AWS::Serverless::HttpApi` creates an **API Gateway HTTP API** (v2), which is faster and cheaper than the older REST API (v1).

**Key properties explained:**

| Property | Value | Effect |
|---|---|---|
| `StageName` | `prod` | All routes are served under `/prod/`. The public URL becomes `https://<id>.execute-api.<region>.amazonaws.com/prod/mcp` |
| `CorsConfiguration.AllowMethods` | `POST` | Only POST requests are allowed by CORS preflight responses |
| `CorsConfiguration.AllowHeaders` | `authorization`, `content-type` | Browser clients may include these headers in cross-origin requests |
| `CorsConfiguration.AllowOrigins` | `*` | Any origin may make CORS requests (suitable for public MCP endpoints) |

CORS preflight (`OPTIONS`) requests are handled automatically by API Gateway when `CorsConfiguration` is set; they do not reach the Lambda function.

### 4.4 Lambda Resource: `LambdaMcpFunction`

```yaml
  LambdaMcpFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: .
      Handler: lambda_function.lambda_handler
      Description: MCP server hosted on Lambda behind HTTP API.
      Events:
        McpRoute:
          Type: HttpApi
          Properties:
            ApiId: !Ref McpHttpApi
            Path: /mcp
            Method: POST
        McpRouteGet:
          Type: HttpApi
          Properties:
            ApiId: !Ref McpHttpApi
            Path: /mcp
            Method: GET
```

**Key properties explained:**

| Property | Value | Effect |
|---|---|---|
| `CodeUri` | `.` | SAM packages all files in the current directory into a ZIP artifact. After `sam deploy`, this becomes an S3 URI in `packaged.yaml` |
| `Handler` | `lambda_function.lambda_handler` | Entry point: file `lambda_function.py`, function `lambda_handler` |
| `Events.McpRoute` | `POST /mcp` | Creates an API Gateway route + Lambda permission allowing POST to `/mcp` |
| `Events.McpRouteGet` | `GET /mcp` | Creates an API Gateway route + Lambda permission allowing GET to `/mcp` |

Both routes use `!Ref McpHttpApi` to bind to the same API Gateway instance defined above. SAM automatically creates the necessary Lambda resource-based policy to allow API Gateway to invoke the function.

### 4.5 Outputs

```yaml
Outputs:
  LambdaMcpFunctionName:
    Description: Lambda function name
    Value: !Ref LambdaMcpFunction

  LambdaMcpFunctionArn:
    Description: Lambda function ARN
    Value: !GetAtt LambdaMcpFunction.Arn

  McpEndpointUrl:
    Description: HTTPS endpoint for Claude-compatible MCP calls
    Value: !Sub "https://${McpHttpApi}.execute-api.${AWS::Region}.amazonaws.com/prod/mcp"
```

CloudFormation exports these values after deployment. They can be retrieved with:

```powershell
aws cloudformation describe-stacks \
  --stack-name lambda-mcp-server \
  --region us-east-1 \
  --query "Stacks[0].Outputs" \
  --output table
```

---

## 5. Deployment Configuration: `samconfig.toml`

`samconfig.toml` stores **default parameter values for the SAM CLI**. It eliminates the need to pass flags on every `sam` command invocation.

```toml
version = 0.1

[default]
[default.global.parameters]
stack_name = "lambda-mcp-server-1-tool"

[default.build.parameters]
cached = true
parallel = true

[default.validate.parameters]
lint = true

[default.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
s3_prefix = "lambda-mcp-server"
region = "us-east-1"
disable_rollback = false
image_repositories = []
```

### 5.1 Structure

The file uses TOML section notation: `[<environment>.<command>.parameters]`. The `default` environment is used when no `--config-env` flag is passed.

### 5.2 Parameter Explanations

#### `[default.global.parameters]`

| Key | Value | Meaning |
|---|---|---|
| `stack_name` | `"lambda-mcp-server-1-tool"` | The CloudFormation stack name used by all SAM commands. Changing this redeploys to a different stack. |

#### `[default.build.parameters]`

| Key | Value | Meaning |
|---|---|---|
| `cached` | `true` | SAM reuses previously built artifacts if source files have not changed, speeding up repeated builds. |
| `parallel` | `true` | Builds multiple Lambda functions concurrently if the template contains more than one function. |

#### `[default.validate.parameters]`

| Key | Value | Meaning |
|---|---|---|
| `lint` | `true` | Enables SAM's built-in linting rules in addition to basic YAML schema validation during `sam validate`. |

#### `[default.deploy.parameters]`

| Key | Value | Meaning |
|---|---|---|
| `capabilities` | `"CAPABILITY_IAM"` | Acknowledges that deployment may create/modify IAM roles (required because SAM creates an execution role for the Lambda function). |
| `confirm_changeset` | `true` | SAM displays the proposed CloudFormation changeset and waits for manual confirmation before applying changes. Set to `false` for CI/CD pipelines. |
| `resolve_s3` | `true` | SAM automatically creates and manages an S3 bucket for storing deployment artifacts. No manual bucket configuration required. |
| `s3_prefix` | `"lambda-mcp-server"` | Prefix applied to S3 object keys for uploaded artifacts, keeping deployments organized. |
| `region` | `"us-east-1"` | Target AWS region for the deployment. |
| `disable_rollback` | `false` | If deployment fails, CloudFormation rolls the stack back to its previous successful state. |
| `image_repositories` | `[]` | Empty — no container image functions are used (ZIP packaging only). |

---

## 6. Build Artifacts: `packaged.yaml` and `build.toml`

### 6.1 `packaged.yaml`

`packaged.yaml` is **auto-generated by `sam deploy`**. It is a copy of `template.yaml` with one key change:

```yaml
# template.yaml (source)
CodeUri: .

# packaged.yaml (generated)
CodeUri: s3://mcp-s3-csi4150/98023ce6da5371e5ef5e4ef2fa51b663
```

The local `CodeUri: .` is replaced with the S3 URI of the uploaded ZIP artifact. This file is what CloudFormation actually consumes during deployment.

**Purpose:** Provides a record of what was deployed and confirms that artifact upload to S3 completed successfully.

### 6.2 `.aws-sam/build.toml`

```toml
# Auto generated by SAM CLI build command

[function_build_definitions.20f35176-5910-490a-9f03-6bc353e5ffec]
codeuri = "C:\Users\jbeem\AppData\Local\Temp\aws-toolkit-vscode\lambda\us-east-1\lambda-mcp-1-tool"
runtime = "python3.12"
architecture = "x86_64"
handler = "lambda_function.lambda_handler"
manifest_hash = "d41d8cd98f00b204e9800998ecf8427e"
packagetype = "Zip"
functions = ["LambdaMcpFunction"]
```

This file is written by `sam build` and tracks what was built. The `manifest_hash` is the MD5 of `requirements.txt`; when it is unchanged between builds and `cached = true`, SAM skips rebuilding to save time.

---

## 7. Application Code: `lambda_function.py`

The Lambda function implements a stateless HTTP/JSON-RPC server. Both versions share the same structural pattern.

### 7.1 Entry Point: `lambda_handler`

```python
def lambda_handler(event, context):
```

AWS Lambda calls this function for every incoming request. The `event` dict contains the full API Gateway proxy payload including headers, body, HTTP method, and request context. The `context` object (not used here) contains runtime metadata.

**Main version flow:**

```
lambda_handler(event, context)
  |
  ├── Extract HTTP method from event
  |     event["requestContext"]["http"]["method"]  (HTTP API v2 format)
  |     event["httpMethod"]                         (fallback / REST API format)
  |
  ├── Reject non-POST with HTTP 405
  |
  ├── _authorize(event)          -- validate Bearer token
  |     Fail → HTTP 401 / 403
  |
  ├── _extract_body(event)       -- parse JSON-RPC request body
  |     Fail → HTTP 400
  |
  ├── Validate jsonrpc == "2.0"
  |     Fail → HTTP 400
  |
  └── Dispatch on rpc_method:
        "initialize"              → _handle_initialize()
        "notifications/initialized" → HTTP 202 empty body
        "tools/list"             → _handle_tools_list()
        "tools/call"             → _handle_tools_call()
        <anything else>          → HTTP 404 Method not found
```

### 7.2 Response Format

All responses follow the API Gateway Lambda Proxy Integration format:

```python
{
    "statusCode": 200,
    "headers": {"Content-Type": "application/json"},
    "body": "<JSON string>"
}
```

The body is always a JSON-RPC 2.0 envelope:

```json
// Success
{"jsonrpc": "2.0", "id": 1, "result": {...}}

// Error
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
```

### 7.3 JSON-RPC Error Codes Used

| Code | Meaning | HTTP Status |
|---|---|---|
| `-32700` | Parse error (invalid JSON body) | 400 |
| `-32600` | Invalid Request (wrong JSON-RPC version or HTTP method) | 400 / 405 |
| `-32601` | Method not found | 404 |
| `-32602` | Invalid params (bad tool arguments) | 200 |
| `-32000` | Server error (network/upstream failure) | 200 |
| `-32001` | Unauthorized | 401 |
| `-32003` | Forbidden | 403 |

---

## 8. MCP Protocol Implementation

### 8.1 `initialize`

Called by MCP clients to establish session parameters.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {}
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
      "name": "lambda-mcp-server",
      "version": "0.3.0"
    },
    "capabilities": {
      "tools": {"listChanged": false}
    }
  }
}
```

`listChanged: false` tells the client that the tool list is static and will not change during the session.

### 8.2 `notifications/initialized`

Sent by the client after `initialize` completes. The server acknowledges with `HTTP 202` and an empty body. No JSON-RPC response is produced because notifications do not have `id` fields.

### 8.3 `tools/list`

Returns all available tools with their input schemas.

**Request:**
```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

**Response:** See [Tool Reference](#9-tool-reference) for the full schema.

### 8.4 `tools/call`

Invokes a named tool with arguments.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "weather",
    "arguments": {"city": "Nashville"}
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"location\": \"Nashville, Tennessee, United States\", ...}"
      }
    ]
  }
}
```

---

## 9. Tool Reference

### 9.1 `echo`

Returns the input text unchanged. Used to verify end-to-end connectivity.

**Input:**
```json
{"text": "hello world"}
```

**Output:** The same string as a text content block.

**Implementation:** `_call_echo` — calls `_require_string(arguments, "text")` and wraps the value in `_tool_result()`.

---

### 9.2 `utc_now`

Returns the current UTC timestamp in ISO 8601 format.

**Input:** No arguments (empty object `{}`).

**Output example:** `"2026-03-07T14:32:00.123456+00:00"`

**Implementation:** `_call_utc_now` — calls `datetime.now(timezone.utc).isoformat()`.

---

### 9.3 `add_numbers`

Adds two numbers and returns the result.

**Input:**
```json
{"a": 3.5, "b": 1.5}
```

**Output:** `"5.0"` (as a text string)

**Implementation:** `_call_add_numbers` — validates both inputs with `_require_number()`, adds them, returns the string representation.

---

### 9.4 `text_stats`

Returns character, word, and line counts for a block of text.

**Input:**
```json
{"text": "Hello world\nThis is a test"}
```

**Output:**
```json
{"characters": 26, "words": 5, "lines": 2}
```

**Implementation:** `_call_text_stats` — uses `len()`, `str.split()`, and `str.splitlines()`. Lines defaults to 1 for text with no newlines.

---

### 9.5 `weather`

Fetches the current weather for a city using the free Open-Meteo API.

**Input:**
```json
{"city": "Boston"}
```

**Output:**
```json
{
  "location": "Boston, Massachusetts, United States",
  "temperature_f": 42.1,
  "feels_like_f": 36.5,
  "wind_mph": 12.3,
  "observed_at": "2026-03-07T14:00"
}
```

**Implementation:** `_call_weather` — two sequential HTTP calls:

1. `GET https://geocoding-api.open-meteo.com/v1/search?name=<city>&count=1&language=en&format=json`
   - Resolves city name to latitude/longitude coordinates.
2. `GET https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&current=temperature_2m,apparent_temperature,wind_speed_10m&temperature_unit=fahrenheit&wind_speed_unit=mph`
   - Fetches current conditions.

**Errors:** If the city is not found or the forecast is unavailable, a JSON-RPC `-32602` or `-32000` error is returned. HTTP failures are caught and wrapped in a `-32000` server error.

**Dependency note:** The main version (`lambda-mcp-1`) uses the `requests` library (bundled via `urllib3`/`idna`). The tool variant uses `urllib.request` from the standard library.

---

## 10. Authentication and Security

The main `lambda_function.py` enforces **Bearer token authentication** on every request.

### 10.1 How It Works

```python
def _authorize(event):
    expected_token = os.environ.get("MCP_BEARER_TOKEN")
    ...
    auth_header = _headers(event).get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return HTTP 401
    if not hmac.compare_digest(token, expected_token):
        return HTTP 403
    return None  # authorized
```

1. The expected token is read from the `MCP_BEARER_TOKEN` environment variable.
2. If the variable is not set, the server returns HTTP 500 (misconfigured) rather than allowing unauthenticated access.
3. The `Authorization` header must use the `Bearer` scheme.
4. `hmac.compare_digest` performs a constant-time comparison to prevent timing attacks.

### 10.2 Setting the Token

The `MCP_BEARER_TOKEN` environment variable must be set in the Lambda function configuration. This is not defined in `template.yaml` (to avoid storing secrets in source control). Set it via:

```powershell
# After deployment, set the secret via AWS CLI
aws lambda update-function-configuration \
  --function-name <LambdaMcpFunctionName> \
  --environment "Variables={PYTHONUNBUFFERED=1,MCP_BEARER_TOKEN=<your-secret-token>}" \
  --region us-east-1
```

Or use AWS Systems Manager Parameter Store / Secrets Manager and reference the value in `template.yaml` with `{{resolve:ssm:/path/to/param}}`.

### 10.3 Simplified Variant (lambda-mcp-1-tool)

The `lambda-mcp-1-tool` variant does **not** implement bearer token authentication. It is suitable only for internal testing or trusted environments.

---

## 11. API Gateway: How It Is Configured

This section explains the full chain from `template.yaml` to a live HTTPS endpoint.

### 11.1 Resource Type: HTTP API vs REST API

`AWS::Serverless::HttpApi` creates a **HTTP API** (API Gateway v2), not a REST API (v1). Key differences:

| Feature | HTTP API (v2) | REST API (v1) |
|---|---|---|
| Latency | Lower | Higher |
| Cost | ~70% cheaper | Standard pricing |
| CORS | Declarative config | Manual gateway responses |
| Lambda integration | Proxy only | Proxy or custom |
| Usage plans/keys | Not supported | Supported |

HTTP API is the correct choice for a simple Lambda proxy integration like this.

### 11.2 Stage and URL Formation

`StageName: prod` results in all routes being mounted under the `/prod` path prefix:

```
Base URL:  https://<api-id>.execute-api.us-east-1.amazonaws.com
Stage:     /prod
Route:     /mcp
Full URL:  https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp
```

The `<api-id>` is a unique identifier assigned by API Gateway at creation time and included in the `McpEndpointUrl` stack output.

### 11.3 Routes and Lambda Integration

SAM translates each `Events` block on the function into:

1. An API Gateway **route** (`METHOD /path`)
2. An API Gateway **integration** (AWS_PROXY type pointing to the Lambda function ARN)
3. A Lambda **resource-based policy** granting `apigateway.amazonaws.com` the `lambda:InvokeFunction` permission

The two configured routes:

| Route | SAM Event Key | Purpose |
|---|---|---|
| `POST /mcp` | `McpRoute` | Primary MCP endpoint for all JSON-RPC calls |
| `GET /mcp` | `McpRouteGet` | Route exists in API Gateway; Lambda returns 405 (main) or passes through (tool variant) |

The GET route exists to allow API Gateway to accept GET requests without returning a 403 route-not-found; the application layer controls the 405 response.

### 11.4 CORS Configuration

```yaml
CorsConfiguration:
  AllowMethods:
    - POST
  AllowHeaders:
    - authorization
    - content-type
  AllowOrigins:
    - "*"
```

When a browser sends a CORS preflight (`OPTIONS`) request:

1. API Gateway intercepts it without invoking Lambda.
2. API Gateway responds with:
   - `Access-Control-Allow-Methods: POST`
   - `Access-Control-Allow-Headers: authorization, content-type`
   - `Access-Control-Allow-Origin: *`
3. The browser then sends the actual `POST` request.

**Important:** `AllowOrigins: "*"` combined with `authorization` in `AllowHeaders` is acceptable for public MCP endpoints. If you need cookies or credentials, you must use a specific origin instead of `*`.

### 11.5 Lambda Proxy Integration Event Format

API Gateway HTTP API forwards a payload to Lambda in the **payload format version 2.0**:

```json
{
  "version": "2.0",
  "routeKey": "POST /mcp",
  "rawPath": "/prod/mcp",
  "requestContext": {
    "http": {
      "method": "POST",
      "path": "/prod/mcp",
      "sourceIp": "1.2.3.4"
    }
  },
  "headers": {
    "authorization": "Bearer <token>",
    "content-type": "application/json"
  },
  "body": "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{}}",
  "isBase64Encoded": false
}
```

The Lambda function reads `event["requestContext"]["http"]["method"]` for the HTTP method, `event["headers"]` for authentication, and `event["body"]` for the JSON-RPC payload.

### 11.6 Lambda Proxy Integration Response Format

Lambda must return a dict matching this structure for API Gateway to construct the HTTP response:

```json
{
  "statusCode": 200,
  "headers": {
    "Content-Type": "application/json"
  },
  "body": "<JSON-encoded string>"
}
```

API Gateway maps `statusCode` to the HTTP status, `headers` to response headers, and `body` to the HTTP response body. The `body` must be a **string** (not a dict); the function calls `json.dumps()` before setting it.

---

## 12. Deployment Procedure

### Step 1: Prerequisites

```powershell
aws sts get-caller-identity      # Confirm valid AWS credentials
sam --version                    # Confirm SAM CLI is installed
python --version                 # Confirm Python 3.12 available
```

### Step 2: Validate Template

```powershell
cd lambda-mcp-1-tool
sam validate --lint
```

Validates `template.yaml` for YAML syntax, schema compliance, and SAM-specific rules.

### Step 3: Build

```powershell
sam build
```

- Reads `template.yaml`
- Installs `requirements.txt` dependencies into the build directory
- Copies function code to `.aws-sam/build/LambdaMcpFunction/`
- Writes `.aws-sam/build.toml`

The `cached = true` and `parallel = true` flags (from `samconfig.toml`) apply automatically.

### Step 4: Deploy

```powershell
sam deploy
```

- Packages the build output and uploads to S3 (because `resolve_s3 = true`)
- Generates `packaged.yaml` with S3 `CodeUri`
- Creates or updates the CloudFormation stack
- Displays the changeset for confirmation (because `confirm_changeset = true`)
- Applies the changeset after approval

### Step 5: Capture the Endpoint URL

```powershell
aws cloudformation describe-stacks \
  --stack-name lambda-mcp-server-1-tool \
  --region us-east-1 \
  --query "Stacks[0].Outputs" \
  --output table
```

The `McpEndpointUrl` output contains the full HTTPS URL.

### Step 6: Set the Bearer Token (main stack only)

```powershell
aws lambda update-function-configuration \
  --function-name <LambdaMcpFunctionName> \
  --environment "Variables={PYTHONUNBUFFERED=1,MCP_BEARER_TOKEN=<token>}" \
  --region us-east-1
```

---

## 13. Functional Verification

All requests require `Content-Type: application/json`. The main stack also requires `Authorization: Bearer <token>`.

### 13.1 Initialize

```powershell
curl -X POST "https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

Expected: HTTP 200, JSON-RPC result with `protocolVersion`, `serverInfo`, `capabilities`.

### 13.2 List Tools

```powershell
curl -X POST "https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

Expected: HTTP 200, tool list containing `echo`, `utc_now`, `add_numbers`, `text_stats`, `weather`.

### 13.3 Call a Tool

```powershell
curl -X POST "https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"weather","arguments":{"city":"Nashville"}}}'
```

Expected: HTTP 200, JSON-RPC result with weather data text content.

### 13.4 Verify Method Enforcement

```powershell
curl -X GET "https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp"
```

Expected: HTTP 405 with `Allow: POST` header.

### 13.5 Verify Auth Enforcement (main stack)

```powershell
curl -X POST "https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/mcp" `
  -H "Content-Type: application/json" `
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

Expected: HTTP 401 with `WWW-Authenticate: Bearer` header.

---

## 14. Change Workflow

### Infrastructure Changes (`template.yaml`, `samconfig.toml`)

1. Edit the file.
2. `sam validate --lint`
3. `sam build`
4. `sam deploy`
5. Verify endpoint responses.

### Application Logic Changes (`lambda_function.py`)

1. Edit the handler or tool code.
2. `sam build`
3. `sam deploy`
4. Run JSON-RPC functional tests.

### Adding a New Tool

1. Add the tool descriptor to the `TOOLS` list (name, description, inputSchema).
2. Implement a `_call_<toolname>(arguments)` function.
3. Add the mapping to `TOOL_HANDLERS`.
4. Build and deploy.
5. Verify with `tools/list` then `tools/call`.

---

## 15. Troubleshooting

### 15.1 `sam validate` Fails

**Symptom:** YAML parse error or schema validation error.

**Action:** Check `template.yaml` for indentation issues, incorrect resource types, or missing required properties. SAM YAML is whitespace-sensitive.

### 15.2 Deployment Fails (CloudFormation Error)

**Common causes:**

| Error | Likely cause | Action |
|---|---|---|
| `InsufficientCapabilities` | `CAPABILITY_IAM` not set | Confirm `samconfig.toml` has `capabilities = "CAPABILITY_IAM"` |
| `ResourceNotFoundException` | Wrong region | Confirm `region = "us-east-1"` in `samconfig.toml` |
| S3 upload failure | No S3 bucket access | Confirm IAM permissions include `s3:PutObject` |
| Rollback | Resource creation failed | Check CloudFormation events in the AWS Console |

### 15.3 HTTP 500 — Server Misconfigured

**Cause:** `MCP_BEARER_TOKEN` environment variable is not set.

**Action:** Set the variable via `aws lambda update-function-configuration`.

### 15.4 HTTP 401 — Unauthorized

**Cause:** Request is missing `Authorization` header or uses a non-Bearer scheme.

**Action:** Add `Authorization: Bearer <token>` to the request headers.

### 15.5 HTTP 403 — Forbidden

**Cause:** Bearer token does not match `MCP_BEARER_TOKEN`.

**Action:** Verify the token value matches what was configured on the Lambda function.

### 15.6 HTTP 400 — Parse Error

**Cause:** Request body is not valid JSON, or `jsonrpc` field is not `"2.0"`.

**Action:** Confirm the body is valid JSON with `"jsonrpc": "2.0"`.

### 15.7 Weather Tool Returns Error

**Cause:** Open-Meteo API is unavailable, or the city name is not recognized.

**Action:**
- Check CloudWatch Logs for the Lambda function for the full exception.
- Retry with a well-known city name.
- Verify outbound internet access is available from the Lambda function (no restrictive VPC configuration).

---

## 16. Decommission

To delete all deployed AWS resources:

```powershell
sam delete --stack-name lambda-mcp-server --region us-east-1
sam delete --stack-name lambda-mcp-server-1-tool --region us-east-1
```

This deletes the CloudFormation stack and all managed resources (Lambda function, API Gateway HTTP API, IAM execution role). The S3 artifact bucket managed by SAM may need to be deleted separately if it was auto-created.

---

## 17. Command Reference

```powershell
# Validate template
sam validate --lint

# Build artifacts
sam build

# Deploy to AWS
sam deploy

# View stack outputs (endpoint URL, function ARN)
aws cloudformation describe-stacks \
  --stack-name lambda-mcp-server \
  --region us-east-1 \
  --query "Stacks[0].Outputs" \
  --output table

# Set bearer token on deployed function
aws lambda update-function-configuration \
  --function-name <LambdaMcpFunctionName> \
  --environment "Variables={PYTHONUNBUFFERED=1,MCP_BEARER_TOKEN=<token>}" \
  --region us-east-1

# Tail CloudWatch logs
aws logs tail /aws/lambda/<LambdaMcpFunctionName> --follow --region us-east-1

# Delete all resources
sam delete --stack-name lambda-mcp-server --region us-east-1
```


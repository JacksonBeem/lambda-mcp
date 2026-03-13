# AWS Toolkit + Connector Full Instructions (Zero to Demo)

Use this as your complete guide and recording script.

## 1) Goal

Build and demo this flow end-to-end:

1. Install AWS Toolkit in VS Code.
2. Configure AWS credentials.
3. Deploy this Lambda MCP server with SAM.
4. Validate MCP methods with curl.
5. Add connector in Toolkit and run a successful tool call.

Project folder:
`c:\Users\jbeem\AppData\Local\Temp\aws-toolkit-vscode\lambda\us-east-1\lambda-mcp-1`

---

## 2) Install everything (commands only, except VS Code)

Run PowerShell as Administrator.

Install Python 3.12:

```powershell
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
```

Install AWS CLI v2:

```powershell
winget install -e --id Amazon.AWSCLI --accept-package-agreements --accept-source-agreements
```

Install AWS SAM CLI:

```powershell
winget install -e --id Amazon.SAM-CLI --accept-package-agreements --accept-source-agreements
```

Install Git:

```powershell
winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
```

Close and reopen terminal, then verify:

```powershell
python --version
pip --version
aws --version
sam --version
git --version
```

If `pip` is missing:

```powershell
python -m ensurepip --upgrade
python -m pip --version
```

---

## 3) AWS account setup (required)

You need an AWS identity with permissions for:

1. CloudFormation
2. Lambda
3. API Gateway
4. IAM role creation for Lambda execution role
5. S3 artifact upload (for SAM deploy)
6. CloudWatch Logs

Two common auth options:

1. IAM Identity Center (recommended for org accounts)
2. IAM access key profile (common for personal/lab accounts)

---

## 4) Configure AWS credentials on your machine

## Option A: IAM Identity Center (recommended)

Run:

```powershell
aws configure sso
```

Provide:

1. SSO start URL
2. SSO region
3. Account
4. Role
5. Profile name (example: `dev-sso`)

Then login:

```powershell
aws sso login --profile dev-sso
aws sts get-caller-identity --profile dev-sso
```

## Option B: Access keys

Run:

```powershell
aws configure --profile dev-keys
```

Provide:

1. AWS access key ID
2. AWS secret access key
3. Default region: `us-east-1`
4. Output format: `json`

Verify:

```powershell
aws sts get-caller-identity --profile dev-keys
```

---

## 5) Install and connect AWS Toolkit in VS Code

Install AWS Toolkit extension from terminal:

```powershell
code --install-extension AmazonWebServices.aws-toolkit-vscode
```

If `code` command is not recognized, use:

```powershell
& "C:\Users\$env:USERNAME\AppData\Local\Programs\Microsoft VS Code\Code.exe" --install-extension AmazonWebServices.aws-toolkit-vscode
```

Then connect account in VS Code:

1. Open VS Code.
2. Open AWS side panel.
3. Click to connect AWS account.
4. Select your profile (`dev-sso` or `dev-keys`).
5. Confirm region is `us-east-1`.

You should now see AWS resources in Toolkit explorer.

---

## 6) Open project and pre-flight checks

In VS Code terminal:

```powershell
cd "c:\Users\jbeem\AppData\Local\Temp\aws-toolkit-vscode\lambda\us-east-1\lambda-mcp-1"
aws sts get-caller-identity
sam validate --lint
```

If `aws sts` fails, fix credential/profile selection first.

If you configured a named profile and want to force it:

```powershell
$env:AWS_PROFILE="dev-sso"
aws sts get-caller-identity
```

---

## 7) Build and deploy with SAM

Run:

```powershell
sam build
sam deploy
```

If prompted to confirm changeset, choose `Y`.

After deploy, get outputs:

```powershell
aws cloudformation describe-stacks `
  --stack-name lambda-mcp-server `
  --region us-east-1 `
  --query "Stacks[0].Outputs" `
  --output table
```

Capture:

1. `LambdaMcpFunctionName`
2. `McpEndpointUrl`

---

## 8) Configure bearer token on Lambda

Set a token:

```powershell
aws lambda update-function-configuration `
  --function-name <LambdaMcpFunctionName> `
  --environment "Variables={PYTHONUNBUFFERED=1,MCP_BEARER_TOKEN=<your-secret-token>}" `
  --region us-east-1
```

Use the same token later in connector headers.

---

## 9) Validate MCP endpoint directly (before connector)

Replace `<endpoint>` and `<token>`.

Initialize:

```powershell
curl -X POST "<endpoint>" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

List tools:

```powershell
curl -X POST "<endpoint>" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

Call tool:

```powershell
curl -X POST "<endpoint>" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <token>" `
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"weather","arguments":{"city":"Boston"}}}'
```

Expected:

1. HTTP 200
2. JSON-RPC response
3. Weather payload in `result.content[0].text`

---

## 10) Add connector in AWS Toolkit

UI text can vary by Toolkit version. Use this exact logic:

1. Open AWS Toolkit panel.
2. Find section named `Connectors`, `MCP`, or `External Tools`.
3. Click `Add` or `Create connector`.
4. Choose HTTP endpoint type.
5. Connector URL: `<McpEndpointUrl>`
6. Add header:
   `Authorization: Bearer <token>`
7. Save connector.
8. Test with:
   - Method: `tools/call`
   - Name: `weather`
   - Arguments: `{"city":"Nashville"}`

Show successful connector response on screen.

---

## 11) Full video script with timestamps

1. `00:00 - 01:30` Intro and architecture.
2. `01:30 - 04:00` Install tools (VS Code, AWS CLI, SAM CLI, Python).
3. `04:00 - 06:00` AWS credential setup (`aws configure sso` or `aws configure`).
4. `06:00 - 08:00` AWS Toolkit install and account connection.
5. `08:00 - 11:00` `sam validate`, `sam build`, `sam deploy`.
6. `11:00 - 13:00` Pull outputs and set bearer token.
7. `13:00 - 16:00` curl verification (`initialize`, `tools/list`, `tools/call`).
8. `16:00 - 19:00` Connector create + connector test call.
9. `19:00 - 21:00` Troubleshooting and recap.

---

## 12) Common problems and fixes

1. `aws sts get-caller-identity` fails:
   Wrong profile or expired SSO session. Re-run login/config.
2. `sam deploy` fails on permissions:
   IAM role lacks CloudFormation/Lambda/APIGateway/IAM/S3 permissions.
3. `401 Unauthorized`:
   Missing `Authorization: Bearer <token>` header.
4. `403 Forbidden`:
   Token does not match `MCP_BEARER_TOKEN`.
5. `Method not found`:
   JSON-RPC `method` value is wrong.
6. Connector test fails but curl works:
   Header not configured in connector or wrong endpoint URL.

Logs:

```powershell
aws logs tail /aws/lambda/<LambdaMcpFunctionName> --follow --region us-east-1
```

---

## 13) Presenter quality checklist

1. Hide account IDs and secrets where needed.
2. Increase terminal font size.
3. Keep one terminal and one code pane visible.
4. Pre-copy endpoint and token to avoid typing errors live.
5. End video with a successful connector tool output visible.

---

## 14) Optional cleanup

Delete resources after demo:

```powershell
sam delete --stack-name lambda-mcp-server --region us-east-1
```

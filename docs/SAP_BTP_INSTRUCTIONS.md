# SAP BTP Instructions for AWS-SAP Hackathon

Participant's manual: https://hackathon-manual.cfapps.ap10.hana.ondemand.com

This guide covers how registered participants log in, deploy to Cloud Foundry, retrieve AI Core and Joule credentials, call the AI models, and deploy Joule capabilities.

## Environment

| Item | Value |
| --- | --- |
| IAS logon tenant | `https://auisywroy.accounts.ondemand.com` |
| Cloud Foundry API | `https://api.cf.ap10.hana.ondemand.com` |
| Cloud Foundry org | `SEAIO_aws-sap-hackathon-si4ykj9d` |
| Team space | `hackathon-<your-team>` |
| Shared AI Core space | `ai-core` |
| CF origin key | `auisywroy-platform` |

## 1. Log on to SAP BTP

Your account was created for you in SAP Cloud Identity Services / IAS. Use your registered email address as your username.

### Activate Your Account And Set Your Password

1. Go to `https://auisywroy.accounts.ondemand.com`.
2. Enter your email address as the username.
3. Use the temporary password provided by the organizer: `Welcome123!`.
4. Set a new password when prompted.
5. Once you land on your profile page, your account is activated.

Use your email address in lowercase. This same IAS password is used for cockpit, Cloud Foundry SSO, and Joule login.

### Log In To BTP Cockpit

Open the cockpit with the IAS identity provider selected:

```text
https://apac.cockpit.btp.cloud.sap/cockpit/?idp=auisywroy.accounts.ondemand.com/
```

Sign in with your email and the new password you set.

You should have read-only subaccount access plus the assigned Joule and service visibility roles. You can browse the subaccount, Cloud Foundry spaces, and service instances, but you cannot change subaccount settings.

## 2. Cloud Foundry CLI And App Deployment

Install the Cloud Foundry CLI v8 first:

```text
https://docs.cloudfoundry.org/cf-cli/install-go-cli.html
```

Log in:

```bash
cf login -a https://api.cf.ap10.hana.ondemand.com --sso
```

When prompted:

1. Choose the alternate/custom identity provider option.
2. Enter this origin key exactly:

```text
auisywroy-platform
```

3. Open the passcode URL printed by the CLI.
4. Sign in with your IAS email and password.
5. Paste the one-time passcode back into the terminal.

Target your org and team space:

```bash
cf target -o "SEAIO_aws-sap-hackathon-si4ykj9d" -s "hackathon-<your-team>"
```

If a command fails with an expired-token message, run `cf login --sso` again.

### Deploy A Simple App

Create a `manifest.yml` in your project folder:

```yaml
---
applications:
  - name: my-team-app
    memory: 256M
    instances: 1
```

Deploy:

```bash
cf push
```

After deployment, run:

```bash
cf app my-team-app
```

The output shows the route/URL for your app.

## 3. Get AI Core And Joule Credentials

Each team has pre-created service credentials for AI Core and Joule / DAS.

Replace `<your-team>` with your team slug. Team slugs are lowercase, spaces and full stops become dashes. Examples: `bap`, `team-ukdw`, `yang-penting-daftar-dulu`, `autoreplenish-ai`.

```bash
# AI Core credentials for model calls
curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/ai-core/<your-team>-key

# Joule / DAS credentials
curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/joule/<your-team>-key

# Team IAS group UUID for Joule visibility_condition
curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/group/<your-team>
```

Keep these credentials private. Do not commit them to git or paste them into shared chats.

The AI Core credential response contains:

```text
clientid
clientsecret
url
serviceurls.AI_API_URL
```

The group response looks like:

```json
{
  "group_id": "<uuid>",
  "display_name": "Hackathon_<team>",
  "team": "<team name>"
}
```

Save the `group_id` if you want to gate a Joule scenario to your team.

## 4. Call The AI Models

Models are deployed through SAP AI Core / Generative AI Hub. Use the AI Core credentials from the keybroker.

### Available Deployments

| Model | Deployment ID |
| --- | --- |
| `gpt-5.4` | `d1a82575de60e02a` |
| `sap-rpt-1.6` | `d76cf689a05d504f` |
| `tabpfn-3.5-plus` | `da450ba3ea929a74`|
| `anthropic--claude-4.6-sonnet` | `dc9594f579d3e4c1`|
| `text-embedding-3-large` | `d5c542b69551fce3`|
| `gemini-3.1-flash-image` | `d5fad5cf7622af7f`|
| `sonar` | `d01c3468af3ad67a`|
| `orchestration` | `d8c092efb8980093` |

Resource group:

```text
default
```

### Get An Access Token

```bash
export TOKEN=$(curl -s -X POST "<url>/oauth/token" \
  -u "<clientid>:<clientsecret>" \
  -d "grant_type=client_credentials" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

export AI_API_URL="<serviceurls.AI_API_URL from your credentials>"
```

### Chat With GPT-5.4

```bash
curl -s -X POST \
  "$AI_API_URL/v2/inference/deployments/d1a82575de60e02a/chat/completions?api-version=2024-12-01-preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H "AI-Resource-Group: default" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Say hello to the hackathon."}],
    "max_completion_tokens": 100
  }'
```

The response is OpenAI-style JSON. The reply is in:

```text
choices[0].message.content
```

### Tabular Prediction With SAP RPT-1.6

SAP RPT is for structured/tabular data. Use `[PREDICT]` for cells to infer.

```bash
curl -s -X POST \
  "$AI_API_URL/v2/inference/deployments/d76cf689a05d504f/predict" \
  -H "Authorization: Bearer $TOKEN" \
  -H "AI-Resource-Group: default" \
  -H "Content-Type: application/json" \
  -d '{
    "prediction_config": {
      "target_columns": [
        {"name": "SALESGROUP", "prediction_placeholder": "[PREDICT]", "task_type": "classification"}
      ]
    },
    "index_column": "ID",
    "rows": [
      {"PRODUCT": "Laptop", "PRICE": 999.99, "ID": "35", "SALESGROUP": "[PREDICT]"},
      {"PRODUCT": "Desktop Computer", "PRICE": 750.5, "ID": "42", "SALESGROUP": "Hardware"},
      {"PRODUCT": "Gaming Mouse", "PRICE": 45.0, "ID": "43", "SALESGROUP": "Accessories"}
    ]
  }'
```

The response contains `predictions`, including predicted values and confidence scores. Use `task_type: "regression"` for numeric targets.

For prompt templating, grounding, and content filtering, use the orchestration deployment:

```text
d8c092efb8980093
```

The SAP Cloud SDK for AI also wraps these APIs: https://sap.github.io/ai-sdk/

## 5. Access Joule And Deploy A Capability

Your account has:

- `Joule End User`: chat with Joule and run capabilities.
- `Joule Developer`: author, compile, and deploy capabilities with the Joule Studio CLI.

### Install Joule Studio CLI

```bash
npm install -g @sap/joule-studio-cli
```

The command is `joule`. Check it with:

```bash
joule --version
```

### Log In To Joule

Use the credentials from your Joule service key. These are in the `/joule/<your-team>-key` response, under `uaa`.

Use `--no-app-tid`:

```bash
joule login --no-app-tid \
  --authurl 'https://auisywroy.authentication.ap10.hana.ondemand.com' \
  --apiurl  'https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap' \
  -c '<uaa.clientid from your joule key>' \
  -s '<uaa.clientsecret from your joule key>'

joule status
```

Expected status:

```text
Logged in
```

Do not use `--sso`. It causes a `redirect_uri` mismatch in this tenant.

### Deploy A Joule Capability

From the folder containing `da.sapdas.yaml`:

```bash
joule deploy --compile .
joule list
joule launch <capability-name>
```

The launch command prints a web client URL like:

```text
https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap/webclient/standalone/<capability-name>
```

Open that URL and invoke your scenario.

### Visibility Conditions

If you gate a scenario with `visibility_condition`, use the IAS group ID from:

```bash
curl -s https://hackathon-keybroker.cfapps.ap10.hana.ondemand.com/group/<your-team>
```

Use the group UUID, not the display name:

```yaml
visibility_condition:
  objects:
    - type: ias_attributes
      attributes:
        - attribute: groups
          match: "ANY"
          values:
            - <group_id from /group/<your-team>>
```

Ungated scenarios are visible to everyone with Joule access.

After any role or group change, log out and log in again to Joule CLI and the web client so the token picks up the change.

## Troubleshooting

### Cockpit login fails

Use the cockpit URL with the `idp` parameter:

```text
https://apac.cockpit.btp.cloud.sap/cockpit/?idp=auisywroy.accounts.ondemand.com/
```

Make sure you activated your IAS account first.

### CF login fails

Use SSO login and origin key `auisywroy-platform`:

```bash
cf login -a https://api.cf.ap10.hana.ondemand.com --sso
```

### Cannot see AI Core / Joule service instances

Participants are added to the shared `ai-core` CF space and should have enough access to view service instances and work with service keys. Log out/in again if the cockpit session was open before roles were assigned.

### Joule access or deployment returns 403

Log out and log in again. Joule reads roles and group memberships from the login token, so stale sessions often continue to fail after role changes.

## Keep Private

Do not share or commit:

- AI Core service key values
- Joule service key values
- `clientsecret`
- access tokens
- generated service credentials

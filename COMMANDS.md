# Craiova Parking Bot - Command Cheat Sheet

**AWS Lambda (API version) + EventBridge + Telegram**

| | |
|---|---|
| Lambda function | `bot-parcare-craiova-api` (Python 3.12, no Docker) |
| Region | `eu-central-1` |
| Schedule | `bot-parcare-trigger`, every 10 minutes |
| Saved state | SSM `/bot-parcare/state` |
| Code | `parking_bot.py` · deploy: `deploy.ps1` |

All commands are for **PowerShell**, run from the project folder.

---

## 0. AWS sign-in

When the AWS CLI reports missing credentials or an expired session:

```powershell
aws login --region eu-central-1
```

Check which account you're signed in to:

```powershell
aws sts get-caller-identity
```

## 1. Manual check

Run the bot once (a normal check, same as the 10-minute schedule):

```powershell
aws lambda invoke --function-name bot-parcare-craiova-api --region eu-central-1 out.json
Get-Content out.json -Encoding UTF8
```

Expected response:

```json
{"statusCode": 200, "body": "urgent=0 info=0 | 🏠 ...: 0 parking lots within 30 m | 📋 Registrations: 0 auctions, 0 waitlist"}
```

## 2. Telegram test alert

Logs in and reads the real site data, then simulates a new parking lot with an open session and 2 free spots.
Sends 3 messages marked **🧪 TEST**. Doesn't change the saved state.

```powershell
Set-Content "$env:TEMP\bot_test.json" '{"test": true}' -Encoding ascii
aws lambda invoke --function-name bot-parcare-craiova-api --region eu-central-1 --payload "fileb://$env:TEMP\bot_test.json" out.json
```

For all 10 repetitions (like a real alert), use `'{"test": true, "repetitions": 10}'`.

## 3. Logs

Live:

```powershell
aws logs tail /aws/lambda/bot-parcare-craiova-api --region eu-central-1 --follow
```

Last hour:

```powershell
aws logs tail /aws/lambda/bot-parcare-craiova-api --region eu-central-1 --since 1h
```

## 4. Start / stop the bot

Stop:

```powershell
aws events disable-rule --name bot-parcare-trigger --region eu-central-1
```

Start:

```powershell
aws events enable-rule --name bot-parcare-trigger --region eu-central-1
```

Check the state (`ENABLED` / `DISABLED`):

```powershell
aws events describe-rule --name bot-parcare-trigger --region eu-central-1 --query State --output text
```

## 5. Saved state / reset

What the bot saw on its last check:

```powershell
aws ssm get-parameter --name /bot-parcare/state --region eu-central-1 --query Parameter.Value --output text
```

Reset. On the next run the bot sends the "started" message with a summary again and saves the current situation as the new baseline. It doesn't alert for what's already on the site.

```powershell
aws ssm delete-parameter --name /bot-parcare/state --region eu-central-1
```

## 6. Update the bot

After editing `parking_bot.py` (uploads the code only, no password prompt):

```powershell
powershell -ExecutionPolicy Bypass -File deploy.ps1
```

If the site email or password changed:

```powershell
powershell -ExecutionPolicy Bypass -File deploy.ps1 -UpdateSecrets
```

The Telegram token is read from `secrets.local.bat`, which is never committed.

## 7. Local dashboard

Health checks, runs over the last 24 h, what the bot sees, logs, and buttons for a **test alert** and **run check now**. Opens at http://127.0.0.1:8765.

```powershell
powershell -ExecutionPolicy Bypass -File dashboard\start.ps1
```

The first start installs the dependencies and builds the frontend. It uses your `aws login` session. If that has expired, the dashboard shows a red banner.
After changes in `dashboard/frontend/src`, run `npm run build` in `dashboard/frontend`. For development with hot reload, run `npm run dev` (port 5173) with the backend started separately.

---

## Alerts the bot sends

| Message | When | How many |
|---|---|---|
| 🚨 PARKING ALERT | A submission session opens for a parking lot near the residence (`can_apply_for_auction`), or new free spots appear (`availability = free` and `status = active`), with the spot numbers | 10 (3 s apart) |
| ℹ️ Change | New parking lot near the residence, waitlist opens, your registrations change, a parking lot disappears | 1 |
| ⚠️ Can't check the site | 3 failed runs in a row (~30 min) | 1 |
| ✅ Working again | First successful run after the warning | 1 |
| 🤖 Bot started | First run (or after a reset) | 1 |

## Troubleshooting

| Problem | Fix |
|---|---|
| `aws` is not recognized | Open a new terminal |
| `NoCredentials` / `ExpiredToken` | `aws login --region eu-central-1` |
| `'charmap' codec can't encode` | Run `$env:PYTHONUTF8 = "1"` first (diacritics / emoji in logs) |
| ⚠️ on Telegram with `wrong password` | `deploy.ps1 -UpdateSecrets` with the new password |
| ⚠️ with another error | Check the logs (section 3). The site has probably changed its API. |

## AWS console

| Service | Link |
|---|---|
| Lambda | https://eu-central-1.console.aws.amazon.com/lambda/home?region=eu-central-1#/functions/bot-parcare-craiova-api |
| CloudWatch Logs | https://eu-central-1.console.aws.amazon.com/cloudwatch/home?region=eu-central-1#logsV2:log-groups |
| EventBridge (schedule) | https://eu-central-1.console.aws.amazon.com/events/home?region=eu-central-1#/rules |
| SSM (state) | https://eu-central-1.console.aws.amazon.com/systems-manager/parameters?region=eu-central-1 |

---

**Bot active:** checks every 10 minutes (~1 s per run) · **Cost:** ~$0/month (within the Lambda free tier) · **Alerts:** Telegram

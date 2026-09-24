# ===================================================================
#  CRAIOVA PARKING BOT - Deploy (AWS Lambda, no Docker)
#
#  Run:      powershell -ExecutionPolicy Bypass -File deploy.ps1
#  Secrets:  -UpdateSecrets  => asks for the site email/password again and updates them
#
#  First run: creates the Lambda function, asks for the site email + password,
#             points the 10-minute schedule at the function and runs a test.
#  Later runs: only update the code (no password prompt).
# ===================================================================
param([switch]$UpdateSecrets)

$Region    = "eu-central-1"
$FuncName  = "bot-parcare-craiova-api"
$IamRole   = "bot-parcare-lambda-role"
$CronRule  = "bot-parcare-trigger"
$Handler   = "parking_bot.handler"
$Here      = $PSScriptRoot

$aws = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $aws) { $aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe" }
if (-not (Test-Path $aws)) { Write-Host "[ERROR] AWS CLI is not installed." -ForegroundColor Red; exit 1 }

function Aws {
    & $aws @args --region $Region
    if ($LASTEXITCODE -ne 0) { throw "AWS command failed: aws $($args -join ' ')" }
}

function Read-Secrets {
    # Telegram settings from secrets.local.bat (never committed), otherwise prompted
    $tg = @{}
    $secretsFile = Join-Path $Here "secrets.local.bat"
    if (Test-Path $secretsFile) {
        foreach ($line in Get-Content $secretsFile) {
            if ($line -match '^\s*set\s+(TELEGRAM_TOKEN|TELEGRAM_CHAT_ID)=(.+?)\s*$') { $tg[$Matches[1]] = $Matches[2] }
        }
    }
    if (-not $tg.TELEGRAM_TOKEN)   { $tg.TELEGRAM_TOKEN   = Read-Host "   Telegram bot token" }
    if (-not $tg.TELEGRAM_CHAT_ID) { $tg.TELEGRAM_CHAT_ID = Read-Host "   Telegram chat ID" }

    Write-Host "Enter your login for the parking site:"
    $email = Read-Host "   Parking site email"
    $sec   = Read-Host "   Parking site password (hidden)" -AsSecureString
    $bstr  = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

    return @{ Variables = @{
        TELEGRAM_TOKEN   = $tg.TELEGRAM_TOKEN
        TELEGRAM_CHAT_ID = $tg.TELEGRAM_CHAT_ID
        SITE_EMAIL       = $email.Trim()
        SITE_PASSWORD    = $password
    } }
}

function With-JsonFile([hashtable]$data, [scriptblock]$action) {
    # Temporary JSON file (UTF-8 without BOM) passed as file://..., deleted right after use
    $tmp = Join-Path $env:TEMP ("parking-bot-" + [guid]::NewGuid() + ".json")
    try {
        [IO.File]::WriteAllText($tmp, ($data | ConvertTo-Json -Compress -Depth 10), (New-Object Text.UTF8Encoding $false))
        & $action "file://$tmp"
    } finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

try {
    Write-Host "`n  === CRAIOVA PARKING BOT - Deploy ===`n" -ForegroundColor Cyan

    # --- [1/5] AWS account + IAM role ---
    $account = Aws sts get-caller-identity --query Account --output text
    Write-Host "[1/5] AWS account: $account"

    # Role for the function: CloudWatch Logs + read/write of its own SSM state (created on first deploy)
    & $aws iam get-role --role-name $IamRole --region $Region *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      Creating IAM role $IamRole ..."
        $trust = @{ Version = "2012-10-17"; Statement = @(@{
            Effect = "Allow"; Principal = @{ Service = "lambda.amazonaws.com" }; Action = "sts:AssumeRole" }) }
        With-JsonFile $trust { param($f) Aws iam create-role --role-name $IamRole --assume-role-policy-document $f | Out-Null }
        Aws iam attach-role-policy --role-name $IamRole `
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole | Out-Null
        $ssmPolicy = @{ Version = "2012-10-17"; Statement = @(@{
            Effect = "Allow"; Action = @("ssm:GetParameter", "ssm:PutParameter")
            Resource = "arn:aws:ssm:${Region}:${account}:parameter/bot-parcare/*" }) }
        With-JsonFile $ssmPolicy { param($f) Aws iam put-role-policy --role-name $IamRole --policy-name ssm-bot-parcare --policy-document $f | Out-Null }
        Write-Host "      Waiting 15 s for the new role to propagate..."
        Start-Sleep -Seconds 15
    }

    # --- [2/5] Code package ---
    $zip = Join-Path $env:TEMP "parking_bot.zip"
    Compress-Archive -Path (Join-Path $Here "parking_bot.py") -DestinationPath $zip -Force
    Write-Host "[2/5] Package created: $zip"

    # --- [3/5] Create or update the function ---
    & $aws lambda get-function --function-name $FuncName --region $Region *> $null
    $exists = ($LASTEXITCODE -eq 0)
    if (-not $exists) {
        Write-Host "[3/5] Creating Lambda function $FuncName ..."
        $roleArn = Aws iam get-role --role-name $IamRole --query Role.Arn --output text
        $envVars = Read-Secrets
        With-JsonFile $envVars {
            param($envFile)
            Aws lambda create-function --function-name $FuncName --runtime python3.12 `
                --handler $Handler --role $roleArn --zip-file "fileb://$zip" `
                --timeout 90 --memory-size 256 --environment $envFile --output text --query FunctionArn | Out-Null
        }
        Aws lambda wait function-active-v2 --function-name $FuncName
        # No automatic retries: a wrong password must not be tried 3 times on every run
        Aws lambda put-function-event-invoke-config --function-name $FuncName --maximum-retry-attempts 0 | Out-Null
    } else {
        Write-Host "[3/5] Function exists - updating the code..."
        Aws lambda update-function-code --function-name $FuncName --zip-file "fileb://$zip" --query LastUpdateStatus --output text | Out-Null
        Aws lambda wait function-updated-v2 --function-name $FuncName
        $currentHandler = Aws lambda get-function-configuration --function-name $FuncName --query Handler --output text
        if ($currentHandler -ne $Handler) {
            Aws lambda update-function-configuration --function-name $FuncName --handler $Handler --query LastUpdateStatus --output text | Out-Null
            Aws lambda wait function-updated-v2 --function-name $FuncName
            Write-Host "      Handler: $currentHandler -> $Handler"
        }
        if ($UpdateSecrets) {
            $envVars = Read-Secrets
            With-JsonFile $envVars {
                param($envFile)
                Aws lambda update-function-configuration --function-name $FuncName --environment $envFile --query LastUpdateStatus --output text | Out-Null
            }
            Aws lambda wait function-updated-v2 --function-name $FuncName
        }
    }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    $funcArn = Aws lambda get-function --function-name $FuncName --query Configuration.FunctionArn --output text
    Write-Host "      OK: $funcArn"

    # --- [4/5] 10-minute schedule -> the function ---
    Write-Host "[4/5] Pointing schedule '$CronRule' at the function..."
    & $aws events describe-rule --name $CronRule --region $Region *> $null
    if ($LASTEXITCODE -ne 0) {
        Aws events put-rule --name $CronRule --schedule-expression "rate(10 minutes)" --state ENABLED | Out-Null
        Write-Host "      Created schedule $CronRule (every 10 minutes)"
    }
    & $aws lambda add-permission --function-name $FuncName --statement-id EventBridgeTrigger `
        --action lambda:InvokeFunction --principal events.amazonaws.com `
        --source-arn "arn:aws:events:${Region}:${account}:rule/$CronRule" --region $Region *> $null
    Aws events put-targets --rule $CronRule --targets "Id=LambdaTarget,Arn=$funcArn" | Out-Null
    $target = Aws events list-targets-by-rule --rule $CronRule --query "Targets[0].Arn" --output text
    Write-Host "      Schedule -> $target"

    # --- [5/5] Test run ---
    Write-Host "[5/5] Running the bot once (test)..."
    $out = Join-Path $env:TEMP "parking_bot_out.json"
    $log = Aws lambda invoke --function-name $FuncName --log-type Tail --query LogResult --output text $out
    Write-Host "`n--- Response ---" -ForegroundColor Cyan
    Get-Content $out -Encoding UTF8
    Write-Host "`n--- Log ---" -ForegroundColor Cyan
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($log))
    Remove-Item $out -Force -ErrorAction SilentlyContinue

    Write-Host "`n  === DEPLOY COMPLETE ===" -ForegroundColor Green
    Write-Host "  Logs: aws logs tail /aws/lambda/$FuncName --region $Region --follow`n"
}
catch {
    Write-Host "`n[ERROR] $_" -ForegroundColor Red
    exit 1
}

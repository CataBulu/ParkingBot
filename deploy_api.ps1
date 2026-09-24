# ===================================================================
#  BOT PARCARE CRAIOVA - Deploy varianta API (fara Docker)
#
#  Rulare:   powershell -ExecutionPolicy Bypass -File deploy_api.ps1
#  Secrete:  -UpdateSecrets  => cere din nou email/parola si le actualizeaza
#
#  Prima rulare: creeaza functia Lambda, cere email + parola site,
#                muta trigger-ul de 10 minute pe functia noua, face un test.
#  Rulari urmatoare: doar actualizeaza codul (nu mai cere parola).
# ===================================================================
param([switch]$UpdateSecrets)

$Region    = "eu-central-1"
$FuncName  = "bot-parcare-craiova-api"
$IamRole   = "bot-parcare-lambda-role"
$CronRule  = "bot-parcare-trigger"
$Here      = $PSScriptRoot

$aws = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $aws) { $aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe" }
if (-not (Test-Path $aws)) { Write-Host "[EROARE] AWS CLI nu este instalat." -ForegroundColor Red; exit 1 }

function Aws {
    & $aws @args --region $Region
    if ($LASTEXITCODE -ne 0) { throw "Comanda AWS a esuat: aws $($args -join ' ')" }
}

function Read-Secrets {
    # Telegram din secrets.local.bat (nu se urca pe git), altfel se cere
    $tg = @{}
    $secretsFile = Join-Path $Here "secrets.local.bat"
    if (Test-Path $secretsFile) {
        foreach ($line in Get-Content $secretsFile) {
            if ($line -match '^\s*set\s+(TELEGRAM_TOKEN|TELEGRAM_CHAT_ID)=(.+?)\s*$') { $tg[$Matches[1]] = $Matches[2] }
        }
    }
    if (-not $tg.TELEGRAM_TOKEN)   { $tg.TELEGRAM_TOKEN   = Read-Host "   Token bot Telegram" }
    if (-not $tg.TELEGRAM_CHAT_ID) { $tg.TELEGRAM_CHAT_ID = Read-Host "   Chat ID Telegram" }

    Write-Host "Introdu datele de acces pentru site-ul de parcare:"
    $email = Read-Host "   Email parcare"
    $sec   = Read-Host "   Parola parcare (nu se afiseaza)" -AsSecureString
    $bstr  = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { $parola = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

    return @{ Variables = @{
        TELEGRAM_TOKEN   = $tg.TELEGRAM_TOKEN
        TELEGRAM_CHAT_ID = $tg.TELEGRAM_CHAT_ID
        SITE_EMAIL       = $email.Trim()
        SITE_PASSWORD    = $parola
    } }
}

function With-EnvFile([hashtable]$envVars, [scriptblock]$action) {
    # Fisier temporar (UTF-8 fara BOM) sters imediat dupa folosire
    $tmp = Join-Path $env:TEMP ("bot-parcare-env-" + [guid]::NewGuid() + ".json")
    try {
        [IO.File]::WriteAllText($tmp, ($envVars | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
        & $action "file://$tmp"
    } finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

try {
    Write-Host "`n  === BOT PARCARE CRAIOVA - Deploy varianta API ===`n" -ForegroundColor Cyan

    # --- [1/5] Cont AWS ---
    $account = Aws sts get-caller-identity --query Account --output text
    Write-Host "[1/5] Cont AWS: $account"

    # --- [2/5] Arhiva cu codul ---
    $zip = Join-Path $env:TEMP "bot_parcare_api.zip"
    Compress-Archive -Path (Join-Path $Here "bot_parcare_api.py") -DestinationPath $zip -Force
    Write-Host "[2/5] Arhiva creata: $zip"

    # --- [3/5] Creez sau actualizez functia ---
    & $aws lambda get-function --function-name $FuncName --region $Region *> $null
    $exists = ($LASTEXITCODE -eq 0)
    if (-not $exists) {
        Write-Host "[3/5] Creez functia Lambda $FuncName ..."
        $roleArn = Aws iam get-role --role-name $IamRole --query Role.Arn --output text
        $envVars = Read-Secrets
        With-EnvFile $envVars {
            param($envFile)
            Aws lambda create-function --function-name $FuncName --runtime python3.12 `
                --handler bot_parcare_api.handler --role $roleArn --zip-file "fileb://$zip" `
                --timeout 90 --memory-size 256 --environment $envFile --output text --query FunctionArn | Out-Null
        }
        Aws lambda wait function-active-v2 --function-name $FuncName
        # Fara reincercari automate: o parola gresita nu trebuie incercata de 3 ori la fiecare rulare
        Aws lambda put-function-event-invoke-config --function-name $FuncName --maximum-retry-attempts 0 | Out-Null
    } else {
        Write-Host "[3/5] Functia exista - actualizez codul..."
        Aws lambda update-function-code --function-name $FuncName --zip-file "fileb://$zip" --query LastUpdateStatus --output text | Out-Null
        Aws lambda wait function-updated-v2 --function-name $FuncName
        if ($UpdateSecrets) {
            $envVars = Read-Secrets
            With-EnvFile $envVars {
                param($envFile)
                Aws lambda update-function-configuration --function-name $FuncName --environment $envFile --query LastUpdateStatus --output text | Out-Null
            }
            Aws lambda wait function-updated-v2 --function-name $FuncName
        }
    }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    $funcArn = Aws lambda get-function --function-name $FuncName --query Configuration.FunctionArn --output text
    Write-Host "      OK: $funcArn"

    # --- [4/5] Trigger-ul de 10 minute -> functia noua ---
    Write-Host "[4/5] Mut trigger-ul '$CronRule' pe functia noua..."
    & $aws lambda add-permission --function-name $FuncName --statement-id EventBridgeTrigger `
        --action lambda:InvokeFunction --principal events.amazonaws.com `
        --source-arn "arn:aws:events:${Region}:${account}:rule/$CronRule" --region $Region *> $null
    Aws events put-targets --rule $CronRule --targets "Id=LambdaTarget,Arn=$funcArn" | Out-Null
    $target = Aws events list-targets-by-rule --rule $CronRule --query "Targets[0].Arn" --output text
    Write-Host "      Trigger -> $target"

    # --- [5/5] Test ---
    Write-Host "[5/5] Rulez botul o data (test)..."
    $out = Join-Path $env:TEMP "bot_parcare_out.json"
    $log = Aws lambda invoke --function-name $FuncName --log-type Tail --query LogResult --output text $out
    Write-Host "`n--- Raspuns ---" -ForegroundColor Cyan
    Get-Content $out -Encoding UTF8
    Write-Host "`n--- Log ---" -ForegroundColor Cyan
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($log))
    Remove-Item $out -Force -ErrorAction SilentlyContinue

    Write-Host "`n  === DEPLOY COMPLET ===" -ForegroundColor Green
    Write-Host "  Loguri: aws logs tail /aws/lambda/$FuncName --region $Region --follow`n"
}
catch {
    Write-Host "`n[EROARE] $_" -ForegroundColor Red
    exit 1
}

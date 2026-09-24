@echo off
setlocal EnableDelayedExpansion

REM ─── Ne asiguram ca rulam din folderul scriptului ───────────────────
cd /d "%~dp0"

echo.
echo  ============================================
echo    BOT PARCARE CRAIOVA - Deploy AWS Lambda
echo  ============================================
echo.

REM ─── CONFIGURARE ────────────────────────────────────────────────────
set AWS_REGION=eu-central-1
set FUNC_NAME=bot-parcare-craiova
set ECR_REPO=bot-parcare-craiova
set IAM_ROLE=bot-parcare-lambda-role
set CRON_RULE=bot-parcare-trigger

REM ─── VERIFICARE DEPENDENTE ───────────────────────────────────────────
where aws >nul 2>&1
IF ERRORLEVEL 1 (
    echo [EROARE] AWS CLI nu este instalat!
    echo          Descarca de la: https://aws.amazon.com/cli/
    pause & exit /b 1
)

where docker >nul 2>&1
IF ERRORLEVEL 1 (
    echo [EROARE] Docker Desktop nu este instalat!
    echo          Descarca de la: https://www.docker.com/products/docker-desktop/
    pause & exit /b 1
)

echo [OK] AWS CLI si Docker detectate.
echo.

REM ─── CREDENTIALE SITE ───────────────────────────────────────────────
echo Introdu datele de acces pentru site-ul de parcare:
echo.
set /p SITE_EMAIL=   Email parcare:
set /p SITE_PASSWORD=   Parola parcare:
echo.

REM Token Telegram din secrets.local.bat (NU se urca pe git) sau introdus manual
if exist "%~dp0secrets.local.bat" call "%~dp0secrets.local.bat"
if not defined TELEGRAM_TOKEN set /p TELEGRAM_TOKEN=   Token bot Telegram:
if not defined TELEGRAM_CHAT_ID set /p TELEGRAM_CHAT_ID=   Chat ID Telegram:
echo [OK] Telegram configurat.
echo.

REM ─── [1/7] OBTINE AWS ACCOUNT ID ────────────────────────────────────
echo [1/7] Verific conexiunea AWS...
FOR /F "usebackq tokens=*" %%A IN (`aws sts get-caller-identity --query Account --output text 2^>nul`) DO SET ACCOUNT_ID=%%A
IF "%ACCOUNT_ID%"=="" (
    echo [EROARE] Nu pot conecta la AWS. Ai rulat 'aws configure'?
    echo          Ai nevoie de: Access Key ID, Secret Access Key, Region: eu-central-1
    pause & exit /b 1
)
set ECR_URI=%ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com/%ECR_REPO%
echo     Account ID : %ACCOUNT_ID%
echo     Region     : %AWS_REGION%
echo     ECR URI    : %ECR_URI%

REM ─── [2/7] CREEZ ECR REPOSITORY ─────────────────────────────────────
echo.
echo [2/7] Creez ECR Repository (daca nu exista deja)...
aws ecr create-repository --repository-name %ECR_REPO% --region %AWS_REGION% >nul 2>&1
echo     OK - %ECR_REPO%

REM ─── [3/7] AUTENTIFICARE ECR ─────────────────────────────────────────
echo.
echo [3/7] Autentificare la ECR...
FOR /F "usebackq tokens=*" %%P IN (`aws ecr get-login-password --region %AWS_REGION%`) DO (
    docker login --username AWS --password "%%P" %ACCOUNT_ID%.dkr.ecr.%AWS_REGION%.amazonaws.com
)
IF ERRORLEVEL 1 (
    echo [EROARE] Autentificare ECR esuata!
    pause & exit /b 1
)

REM ─── [4/7] BUILD DOCKER IMAGE ────────────────────────────────────────
echo.
echo [4/7] Build Docker image...
echo       (Prima data dureaza 5-10 minute - descarca Chromium)
echo.
docker build --no-cache --platform linux/amd64 --provenance=false -t %ECR_REPO% .
IF ERRORLEVEL 1 (
    echo [EROARE] Docker build esuat!
    pause & exit /b 1
)
echo.
echo     Build complet!

REM ─── [5/7] PUSH LA ECR ───────────────────────────────────────────────
echo.
echo [5/7] Trimit imaginea la AWS ECR...
docker tag %ECR_REPO%:latest %ECR_URI%:latest
docker push %ECR_URI%:latest
IF ERRORLEVEL 1 (
    echo [EROARE] Push ECR esuat!
    pause & exit /b 1
)
echo     Imaginea e in ECR.

REM ─── [6/7] ROL IAM + PERMISIUNI ──────────────────────────────────────
echo.
echo [6/7] Configurez rolul IAM...

REM Creez rolul (ignora eroarea daca exista deja)
aws iam create-role ^
    --role-name %IAM_ROLE% ^
    --assume-role-policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}" ^
    >nul 2>&1

REM Attach policy de baza Lambda (CloudWatch Logs)
aws iam attach-role-policy ^
    --role-name %IAM_ROLE% ^
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole ^
    >nul 2>&1

REM Attach policy SSM (pentru a salva/citi baseline-ul)
aws iam put-role-policy ^
    --role-name %IAM_ROLE% ^
    --policy-name ssm-bot-parcare ^
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"ssm:GetParameter\",\"ssm:PutParameter\"],\"Resource\":\"arn:aws:ssm:%AWS_REGION%:%ACCOUNT_ID%:parameter/bot-parcare/*\"}]}" ^
    >nul 2>&1

echo     Astept propagarea rolului IAM (15 secunde)...
timeout /t 15 /nobreak >nul

FOR /F "usebackq tokens=*" %%A IN (`aws iam get-role --role-name %IAM_ROLE% --query Role.Arn --output text`) DO SET ROLE_ARN=%%A
echo     Rol ARN: %ROLE_ARN%

REM ─── Scriem env vars intr-un JSON via Python (evita probleme cu @ : = in CMD) ──
echo     Generez fisier env_vars.json...
set ENV_FILE=%~dp0env_vars.json
python -c "import json,sys; open(sys.argv[1],'w').write(json.dumps({'Variables':{'TELEGRAM_TOKEN':sys.argv[2],'TELEGRAM_CHAT_ID':sys.argv[3],'SITE_EMAIL':sys.argv[4],'SITE_PASSWORD':sys.argv[5]}}))" "%ENV_FILE%" "%TELEGRAM_TOKEN%" "%TELEGRAM_CHAT_ID%" "%SITE_EMAIL%" "%SITE_PASSWORD%"
IF ERRORLEVEL 1 (
    echo [EROARE] Nu am putut genera env_vars.json. Python instalat?
    pause & exit /b 1
)

REM ─── [7/7] CREEZ SAU ACTUALIZEZ LAMBDA ───────────────────────────────
echo.
echo [7/7] Deploy Lambda Function...

aws lambda get-function --function-name %FUNC_NAME% --region %AWS_REGION% >nul 2>&1
IF ERRORLEVEL 1 GOTO CREATE_LAMBDA
GOTO UPDATE_LAMBDA

:CREATE_LAMBDA
echo     Creez functia Lambda noua...
aws lambda create-function --function-name %FUNC_NAME% --package-type Image --code ImageUri=%ECR_URI%:latest --role %ROLE_ARN% --timeout 300 --memory-size 1024 --region %AWS_REGION% --environment file://%ENV_FILE%
IF ERRORLEVEL 1 (
    echo [EROARE] Create Lambda esuat!
    del "%ENV_FILE%" >nul 2>&1
    pause & exit /b 1
)
GOTO LAMBDA_DONE

:UPDATE_LAMBDA
echo     Functia exista - actualizez codul...
aws lambda update-function-code --function-name %FUNC_NAME% --image-uri %ECR_URI%:latest --region %AWS_REGION% >nul
echo     Astept finalizarea update-ului (30 secunde)...
timeout /t 30 /nobreak >nul
echo     Actualizez configuratia...
aws lambda update-function-configuration --function-name %FUNC_NAME% --timeout 300 --memory-size 1024 --region %AWS_REGION% --environment file://%ENV_FILE% >nul
GOTO LAMBDA_DONE

:LAMBDA_DONE
echo     Lambda OK!
del "%ENV_FILE%" >nul 2>&1

REM ─── [+] CLOUDWATCH EVENTS TRIGGER (la 10 minute) ─────────────────────
echo.
echo [+] Configurez CloudWatch cron (la fiecare 10 minute)...

aws events put-rule ^
    --name %CRON_RULE% ^
    --schedule-expression "rate(10 minutes)" ^
    --state ENABLED ^
    --region %AWS_REGION% ^
    >nul

FOR /F "usebackq tokens=*" %%A IN (`aws lambda get-function --function-name %FUNC_NAME% --region %AWS_REGION% --query Configuration.FunctionArn --output text`) DO SET LAMBDA_ARN=%%A

aws lambda add-permission ^
    --function-name %FUNC_NAME% ^
    --statement-id CloudWatchTrigger ^
    --action lambda:InvokeFunction ^
    --principal events.amazonaws.com ^
    --source-arn arn:aws:events:%AWS_REGION%:%ACCOUNT_ID%:rule/%CRON_RULE% ^
    --region %AWS_REGION% ^
    >nul 2>&1

FOR /F "usebackq tokens=*" %%A IN (`aws events list-rules --name-prefix %CRON_RULE% --region %AWS_REGION% --query "Rules[0].Arn" --output text`) DO SET RULE_ARN=%%A

aws events put-targets ^
    --rule %CRON_RULE% ^
    --targets "Id=LambdaTarget,Arn=%LAMBDA_ARN%" ^
    --region %AWS_REGION% ^
    >nul

echo     Trigger activ! Lambda se va executa la fiecare 10 minute.

REM ─── SUMMARY ───────────────────────────────────────────────────────────
echo.
echo  ============================================
echo    DEPLOY COMPLET! Botul este ACTIV!
echo  ============================================
echo.
echo  Pasi urmatori:
echo.
echo  1. Testeaza manual acum (prima rulare seteaza baseline):
echo     aws lambda invoke --function-name %FUNC_NAME% --region %AWS_REGION% out.json
echo     type out.json
echo.
echo  2. Urmareste logurile live in CloudWatch:
echo     https://console.aws.amazon.com/cloudwatch/home?region=%AWS_REGION%#logsV2:log-groups
echo.
echo  3. Daca vrei sa OPRESTI botul:
echo     aws events disable-rule --name %CRON_RULE% --region %AWS_REGION%
echo.
echo  4. Daca vrei sa REPORNESTI botul:
echo     aws events enable-rule --name %CRON_RULE% --region %AWS_REGION%
echo.
echo  5. Daca vrei sa RESETEZI baseline-ul (ex: dupa ce ai luat un loc):
echo     aws ssm delete-parameter --name /bot-parcare/baseline --region %AWS_REGION%
echo.
pause

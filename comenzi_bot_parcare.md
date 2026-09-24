# Bot Parcare Craiova - Comenzi utile

**AWS Lambda (varianta API) + EventBridge + Telegram**

| | |
|---|---|
| Functie Lambda | `bot-parcare-craiova-api` (Python 3.12, fara Docker) |
| Regiune | `eu-central-1` |
| Trigger | `bot-parcare-trigger` - la fiecare 10 minute |
| Stare salvata | SSM `/bot-parcare/state` |
| Cod | `bot_parcare_api.py` · deploy: `deploy_api.ps1` |

Toate comenzile sunt pentru **PowerShell**, rulate din folderul proiectului.

---

## 0. Autentificare AWS

Cand AWS CLI spune ca nu are credentiale sau ca sesiunea a expirat:

```powershell
aws login --region eu-central-1
```

Verificare cont:

```powershell
aws sts get-caller-identity
```

## 1. Verificare manuala

Ruleaza botul o data (verificare normala, ca la fiecare 10 minute):

```powershell
aws lambda invoke --function-name bot-parcare-craiova-api --region eu-central-1 out.json
Get-Content out.json -Encoding UTF8
```

Raspuns asteptat:

```json
{"statusCode": 200, "body": "urgente=0 info=0 | 🏠 ...: 0 parcari in 30 m | 📋 Inscrieri: 0 licitatii, 0 lista de asteptare"}
```

## 2. Alerta de test pe Telegram

Se logheaza pe site si citeste datele reale, apoi simuleaza o parcare noua cu sesiune deschisa si 2 locuri libere.
Trimite 3 mesaje marcate **🧪 TEST**. Nu modifica starea salvata.

```powershell
Set-Content "$env:TEMP\bot_test.json" '{"test": true}' -Encoding ascii
aws lambda invoke --function-name bot-parcare-craiova-api --region eu-central-1 --payload "fileb://$env:TEMP\bot_test.json" out.json
```

Pentru toate cele 10 repetari (ca la o alerta reala), foloseste `'{"test": true, "repetari": 10}'`.

## 3. Loguri

Live:

```powershell
aws logs tail /aws/lambda/bot-parcare-craiova-api --region eu-central-1 --follow
```

Ultima ora:

```powershell
aws logs tail /aws/lambda/bot-parcare-craiova-api --region eu-central-1 --since 1h
```

## 4. Pornire / Oprire bot

Oprire:

```powershell
aws events disable-rule --name bot-parcare-trigger --region eu-central-1
```

Pornire:

```powershell
aws events enable-rule --name bot-parcare-trigger --region eu-central-1
```

Verificare stare (`ENABLED` / `DISABLED`):

```powershell
aws events describe-rule --name bot-parcare-trigger --region eu-central-1 --query State --output text
```

## 5. Stare salvata / Reset

Ce a vazut botul la ultima verificare:

```powershell
aws ssm get-parameter --name /bot-parcare/state --region eu-central-1 --query Parameter.Value --output text
```

Reset. La urmatoarea rulare botul trimite din nou mesajul "pornit" cu rezumatul si salveaza situatia curenta ca noua referinta. Nu alerteaza pentru ce exista deja pe site.

```powershell
aws ssm delete-parameter --name /bot-parcare/state --region eu-central-1
```

## 6. Update bot

Dupa ce modifici `bot_parcare_api.py` (urca doar codul, nu cere parola):

```powershell
powershell -ExecutionPolicy Bypass -File deploy_api.ps1
```

Daca s-a schimbat email-ul sau parola de pe site:

```powershell
powershell -ExecutionPolicy Bypass -File deploy_api.ps1 -UpdateSecrets
```

Token-ul Telegram se citeste din `secrets.local.bat` (nu se urca pe git).

---

## Ce alerte trimite botul

| Mesaj | Cand | De cate ori |
|---|---|---|
| 🚨 ALERTĂ PARCARE | Se deschide sesiunea de depunere pentru o parcare de langa imobil (`can_apply_for_auction`) sau apar locuri libere noi (`availability = free` si `status = active`), cu numerele locurilor | 10 (la 3 sec) |
| ℹ️ Schimbare | Parcare noua langa imobil, se deschide lista de asteptare, se schimba inscrierile tale, o parcare dispare | 1 |
| ⚠️ Nu mai pot verifica site-ul | 3 rulari esuate la rand (~30 min) | 1 |
| ✅ Functioneaza din nou | Prima rulare reusita dupa avertizare | 1 |
| 🤖 Bot pornit | Prima rulare (sau dupa reset) | 1 |

## Depanare

| Problema | Solutie |
|---|---|
| `aws` nu e recunoscut | Deschide un terminal nou |
| `NoCredentials` / `ExpiredToken` | `aws login --region eu-central-1` |
| `'charmap' codec can't encode` | Ruleaza intai `$env:PYTHONUTF8 = "1"` (diacritice / emoji in loguri) |
| ⚠️ pe Telegram cu `parola gresita` | `deploy_api.ps1 -UpdateSecrets` cu parola noua |
| ⚠️ cu alta eroare | Verifica logurile (sectiunea 3). Site-ul si-a schimbat probabil API-ul. |

## Console AWS

| Serviciu | Link |
|---|---|
| Lambda | https://eu-central-1.console.aws.amazon.com/lambda/home?region=eu-central-1#/functions/bot-parcare-craiova-api |
| CloudWatch Logs | https://eu-central-1.console.aws.amazon.com/cloudwatch/home?region=eu-central-1#logsV2:log-groups |
| EventBridge (trigger) | https://eu-central-1.console.aws.amazon.com/events/home?region=eu-central-1#/rules |
| SSM (stare) | https://eu-central-1.console.aws.amazon.com/systems-manager/parameters?region=eu-central-1 |

---

**Bot activ:** verifica la fiecare 10 minute (~1 sec per rulare) · **Cost:** ~0 $/luna (in free tier-ul Lambda) · **Alerte:** Telegram

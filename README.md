# ResQra Backend

FastAPI backend for ResQra, a flood emergency response system. It provides resident auth, incident intake, rescue queue operations, team dispatch, public advisories, maps, chat, and the current v0 AI assistant seams.

Frontend repository:

```text
https://github.com/ResQra/frontend.git
```

## Tech Stack

- FastAPI
- DynamoDB through `boto3`
- JWT auth with resident and coordinator roles
- Groq LLM for current v0 resident chat/profile extraction and coordinator assistant
- OSM/Nominatim geocoding
- Future Strands agents integration through `app/agents_gateway/gateway.py`

## Clone And Run Locally

```bash
git clone https://github.com/ResQra/Backend.git
cd Backend
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, then run:

```bash
python scripts/create_tables.py
python scripts/create_admin.py resqra-admin <password> "Control Room"
python scripts/seed.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend health check:

```text
http://127.0.0.1:8000/api/health
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Required Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Important values:

```env
JWT_SECRET=replace-with-a-secure-random-secret
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
DYNAMODB_ENDPOINT_URL=
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
OTP_DEV_MODE=true
```

Generate a production JWT secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## AWS Credentials

For local development, the senior can provide AWS credentials in either of these ways:

1. Put credentials in `.env`:

```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
```

2. Or configure the standard AWS credentials file outside the repo:

```text
~/.aws/credentials
```

Example:

```ini
[default]
aws_access_key_id=...
aws_secret_access_key=...
```

For AWS deployment, prefer IAM roles or securely managed environment variables instead of committing keys.

## API Keys

Groq is used by the current v0 AI layer:

```env
GROQ_API_KEY=your-groq-key
```

Get the key from:

```text
https://console.groq.com/
```

OpenStreetMap/Nominatim geocoding does not require an API key.

## Database Setup

Create DynamoDB tables:

```bash
python scripts/create_tables.py
```

Seed demo rescue teams and shelters:

```bash
python scripts/seed.py
```

Create a coordinator account:

```bash
python scripts/create_admin.py resqra-admin <password> "Control Room"
```

The frontend coordinator login uses:

```text
/login -> Official
```

## Core API Areas

- `/api/auth/*`: resident OTP and coordinator login
- `/api/incidents/*`: resident incident creation and status tracking
- `/api/chat/*`: resident chat assistant
- `/api/public/*`: public shelters, reports, and guides
- `/api/ops/*`: coordinator-only queue, action board, map data, teams, reports, and assistant

Coordinator routes require JWT role:

```text
coordinator
```

## Strands Agent Integration Plan

The backend is already structured so future Strands agents plug in without changing frontend contracts.

Integration seam:

```text
app/agents_gateway/gateway.py
```

Current v0 functions:

- `resident_chat(...)`: current Groq-backed resident assistant
- `coordinator_assistant(...)`: current Groq-backed ops assistant
- `recommend_team(...)`: deterministic allocation recommendation
- `intake_extract(...)`: placeholder for IntakeAgent
- `triage_score(...)`: placeholder for TriageAgent

When Strands agents are ready, replace the implementation inside this gateway while keeping router responses stable.

## AWS Deployment Notes

Likely deployment shape:

- FastAPI backend on AWS App Runner, ECS/Fargate, EC2, or Lambda container
- DynamoDB in `ap-south-1`
- Secrets stored in AWS Secrets Manager, Parameter Store, or hosting provider env vars
- Frontend deployed to Vercel

Production backend env must include:

```env
JWT_SECRET=<strong-secret>
AWS_REGION=ap-south-1
GROQ_API_KEY=<groq-key>
CORS_ORIGINS=https://your-vercel-app.vercel.app
OTP_DEV_MODE=false
```

If using real SMS/WhatsApp OTP, implement delivery in:

```text
app/auth/otp.py
```

## Local Verification

```bash
python -m py_compile app/routers/ops.py app/models.py app/db/repos/users.py
```

Smoke test, after backend and DynamoDB are configured:

```bash
python scripts/smoke_test.py
```

from pathlib import Path

from pydantic_settings import BaseSettings

# Absolute anchor: backend/.env must load no matter which directory the
# process starts from (repo root, backend/, systemd, docker WORKDIR...).
# A relative ".env" silently drops GROQ/AWS keys by cwd — which used to
# 503 the debate loop, resident chat, and ops assistant with no warning.
_BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # Auth
    jwt_secret: str = "dev-secret-change-me-in-prod"
    jwt_algorithm: str = "HS256"
    token_expire_minutes: int = 60 * 24  # 24h, hackathon-friendly
    # OPTIONAL legacy gate for coordinator logins (empty = open). Admin
    # accounts now use username+password; residents use phone OTP.
    coordinator_access_code: str = ""

    # AWS / DynamoDB
    aws_region: str = "ap-south-1"
    # Option A (simplest): put AWS keys right here in .env
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    # Option B: leave the above empty and use ~/.aws/credentials or env vars
    # Set to http://localhost:8000 to use DynamoDB Local instead of real AWS
    dynamodb_endpoint_url: str | None = None

    # Comma-separated list; add the Vercel frontend URL when deployed.
    # :4173 is the embedded God's Eye globe (third_party/gods-eye-view dev
    # server) — its ResQra Ops layer fetches /api/ops/map-data directly.
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:4173"

    # LLM (Groq, free tier) — powers chat + profile extraction
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Gemini — ears/mouth/eyes of the coordinator AI (Phase 6): live voice
    # transcription, image understanding, TTS replies. Empty = those
    # endpoints answer 503 honestly; text reasoning stays on Groq.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_tts_voice: str = "Kore"
    # Gemini Live bidirectional voice (duplex conversation). First entry is
    # tried first; the proxy falls through the list when Google reports an
    # unknown/retired model, so a model sunset degrades to the next instead
    # of killing voice. Override with GEMINI_LIVE_MODEL in .env.
    gemini_live_model: str = "gemini-2.5-flash-native-audio-latest"

    # Amazon Bedrock text provider (optional, hackathon-aligned). Empty =
    # stay on Groq. Set BEDROCK_TEXT_MODEL (e.g. amazon.nova-lite-v1:0) plus
    # real AWS creds to route llm.chat_completion through Bedrock Converse.
    # Voice stays on Gemini Live regardless (duplex audio is the low-latency
    # path; swapping the text brain does not lower voice latency).
    bedrock_text_model: str = ""
    bedrock_region: str = "us-east-1"

    # Strands agent runtime. Empty URL = use the local agents/ project in
    # dev mode; set to the deployed agent base URL after deployment, e.g.
    # https://agent.example.com  (POST {url}/tasks with a task envelope).
    resqra_agent_url: str = ""
    # Optional override for where the standalone agents/ project lives when
    # running agents locally (defaults to <repo root>/agents).
    resqra_agents_path: str = ""

    # OTP login (residents). Dev mode returns the code in the API response
    # and logs it instead of sending SMS — flip to false once an SMS
    # provider is wired into app/auth/otp.py::send_sms.
    otp_dev_mode: bool = True

    model_config = {"env_file": _BACKEND_DIR / ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

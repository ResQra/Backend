from pydantic_settings import BaseSettings


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

    # Comma-separated list; add the Vercel frontend URL when deployed
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # LLM (Groq, free tier) — powers chat + profile extraction
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

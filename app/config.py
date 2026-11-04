from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    llm_provider: str = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    featherless_api_key: str = ""
    featherless_model: str = "Qwen/Qwen2.5-7B-Instruct"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    hf_token: str = ""


settings = Settings()

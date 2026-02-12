from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    server_port: int = Field(default=8000, alias="SERVER_PORT")

    llm_backend_url: str = Field(default="http://127.0.0.1:8080", alias="LLM_BACKEND_URL")
    whisper_backend_url: str = Field(default="http://127.0.0.1:8081", alias="WHISPER_BACKEND_URL")

    llm_model_name: str = Field(default="", alias="LLM_MODEL_NAME")
    whisper_model_name: str = Field(default="", alias="WHISPER_MODEL_NAME")

    llm_start_command: str = Field(default="", alias="LLM_START_COMMAND")
    llm_stop_command: str = Field(default="", alias="LLM_STOP_COMMAND")
    whisper_start_command: str = Field(default="", alias="WHISPER_START_COMMAND")
    whisper_stop_command: str = Field(default="", alias="WHISPER_STOP_COMMAND")

    auto_switch_backend: bool = Field(default=True, alias="AUTO_SWITCH_BACKEND")
    responses_mode: str = Field(default="map", alias="RESPONSES_MODE")

    models_list_mode: str = Field(default="active", alias="MODELS_LIST_MODE")

    llm_health_path: str = Field(default="/v1/models", alias="LLM_HEALTH_PATH")
    whisper_health_path: str = Field(default="/v1/models", alias="WHISPER_HEALTH_PATH")

    switch_timeout_seconds: float = Field(default=30.0, alias="SWITCH_TIMEOUT_SECONDS")

    models_dir: str = Field(default="C:\\models", alias="MODELS_DIR")
    huggingface_token: str = Field(default="", alias="HF_TOKEN")


settings = Settings()

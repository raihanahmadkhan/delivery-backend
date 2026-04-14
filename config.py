import json
from pydantic_settings import BaseSettings, SettingsConfigDict
_LOCALHOST_ORIGINS = ['http://localhost:5173', 'http://localhost:3000', 'http://127.0.0.1:5173']

class Settings(BaseSettings):
    app_name: str = 'Delivery Route Optimizer API'
    app_version: str = '1.0.0'
    debug: bool = False
    cors_origins: str = ''
    max_nodes: int = 200
    max_iterations: int = 500
    max_population: int = 200
    max_ants: int = 100
    max_particles: int = 100
    model_config = SettingsConfigDict(env_prefix='APP_', case_sensitive=False)

def get_cors_origins() -> list[str]:
    """
    Parse settings.cors_origins string into a list of allowed origins.
    Called once at app startup so the result reflects the current env var.
    """
    raw = (settings.cors_origins or '').strip()
    if not raw:
        return _LOCALHOST_ORIGINS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(o).strip() for o in parsed if str(o).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    return [o.strip() for o in raw.split(',') if o.strip()]
settings = Settings()
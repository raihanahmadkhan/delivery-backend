from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str    = "Delivery Route Optimizer API"
    app_version: str = "1.0.0"
    debug: bool      = False

    # Override in production via APP_CORS_ORIGINS env var (JSON array string)
    # e.g. APP_CORS_ORIGINS='["https://your-app.netlify.app"]'
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    max_nodes: int      = 200
    max_iterations: int = 500
    max_population: int = 200
    max_ants: int       = 100
    max_particles: int  = 100

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        case_sensitive=False,
    )


settings = Settings()

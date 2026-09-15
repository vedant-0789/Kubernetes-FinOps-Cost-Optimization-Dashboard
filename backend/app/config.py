import os

try:
    from pydantic_settings import BaseSettings
except ImportError:
    try:
        from pydantic import BaseSettings
    except ImportError:
        class BaseSettings:
            pass

class Settings(BaseSettings):
    PROJECT_NAME: str = "Kubernetes FinOps & Cost Optimization Dashboard"
    MOCK_MODE: bool = True
    DATABASE_URL: str = "sqlite:///./finops.db"
    
    # Pricing Defaults (AWS/GCP average equivalent)
    DEFAULT_CPU_HOURLY_RATE: float = 0.048  # $ / vCPU-hour
    DEFAULT_RAM_HOURLY_RATE: float = 0.006  # $ / GB-hour
    
    # Zombie Detection Rules
    IDLE_CPU_THRESHOLD_PCT: float = 5.0    # CPU usage below 5%
    IDLE_MEM_THRESHOLD_PCT: float = 10.0   # Memory usage below 10%
    EVALUATION_WINDOW_HOURS: int = 24       # Sustained period in hours
    
    # Right-Sizing Safety Buffer
    SAFETY_BUFFER_PCT: float = 20.0        # p95 usage + 20%
    
    # Auto Remediation
    AUTO_REMEDIATION_ENABLED: bool = False

settings = Settings()

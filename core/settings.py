from pydantic_settings import BaseSettings
from .constants import ENV_PREFIX
from hyperlocal_platform.core.enums.environment_enum import EnvironmentEnum

class OrdersSettings(BaseSettings):
    PG_DATABASE_URL:str
    MONGO_DB_URL:str
    ENVIRONMENT:EnvironmentEnum

    model_config={
        'env_prefix':ENV_PREFIX,
        'case_sensitive':False
    }
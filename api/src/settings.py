from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_api_')

    notification_timeout: float = Field(default=5.0)

    capture_loop_sleep_duration: float = Field(default=3.0)
    refund_loop_sleep_duration: float = Field(default=3.0)
    notify_charge_loop_sleep_duration: float = Field(default=1.0)
    payments_polling_loop_sleep_duration: float = Field(default=1.0)


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_postgres_')

    host: str = Field(default='127.0.0.1')
    port: int = Field(default=5432)
    user: str = Field(default='postgres')
    password: str = Field(default='postgres')
    db: str = Field(default='bill')

    def get_url(self, driver: str | None, db: str | None = None):
        scheme = f'postgresql{f'+{driver}' if driver else ''}'
        return f'{scheme}://{self.user}:{self.password}@{self.host}:{self.port}/{db or self.db}'


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_kafka_')


class YookassaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_yookassa_')

    shop_id: str
    secret_key: str
    base_url: str = Field(default='https://api.yookassa.ru')


settings = Settings()
pg_settings = PostgresSettings()
yookassa_settings = YookassaSettings()  # type: ignore
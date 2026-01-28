from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_api_')

    notification_timeout: float = Field(default=5.0)

    refund_loop_sleep_duration: float = Field(default=3.0)
    payments_polling_loop_sleep_duration: float = Field(default=1.0)
    handlers_notification_loop_sleep_duration: float = Field(default=1.0)


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_postgres_')

    host: str = Field(default='127.0.0.1')
    port: int = Field(default=5432)
    user: str
    password: str
    db: str

    def get_url(self, driver: str | None, db: str | None = None):
        scheme = f'postgresql{f'+{driver}' if driver else ''}'
        return f'{scheme}://{self.user}:{self.password}@{self.host}:{self.port}/{db or self.db}'


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_kafka_')

    bootstrap_servers: str = Field(default='localhost:19092')


class YookassaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='allow', env_prefix='bill_yookassa_')

    shop_id: str = Field(default='1245745')  # Задано для удобства, в реальном проекте такого не допускать!
    secret_key: str = Field(default='test_EYVo1Qh3f5Yg2VJk-x6KNPBrF2AIokmz6-WcNOK84Do')
    base_url: str = Field(default='https://api.yookassa.ru')
    connection_timeout_sec: float = 60.0


settings = Settings()
pg_settings = PostgresSettings()  # type: ignore
kafka_settings = KafkaSettings()
yookassa_settings = YookassaSettings()  # type: ignore
import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROJECT_NAME: str = "NHCX Session Logger API"
    PROJECT_VERSION: str = "1.0.0"

    # ── MySQL / Cloud SQL ──────────────────────────────────────────────────
    MYSQL_USER: str = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD")
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "34.14.140.183")
    MYSQL_PORT: str = os.getenv("MYSQL_PORT", "3306")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "nhcx")
    MYSQL_QUERY: str = os.getenv("MYSQL_QUERY", "charset=utf8mb4")

    # ── SSL Certificates (same files as rest of repo) ─────────────────────
    MYSQL_SSL_CA: str = os.getenv("MYSQL_SSL_CA")
    MYSQL_SSL_CERT: str = os.getenv("MYSQL_SSL_CERT")
    MYSQL_SSL_KEY: str = os.getenv("MYSQL_SSL_KEY")

    @property
    def DATABASE_URL(self) -> str:
        password = urllib.parse.quote_plus(self.MYSQL_PASSWORD) if self.MYSQL_PASSWORD else ""
        url = (
            f"mysql+pymysql://{self.MYSQL_USER}:{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        )
        if self.MYSQL_QUERY:
            url += f"?{self.MYSQL_QUERY}"
        return url


settings = Settings()

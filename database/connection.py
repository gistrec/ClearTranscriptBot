"""SQLAlchemy engine and session configuration."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = os.getenv("MYSQL_PORT")
MYSQL_DB = os.getenv("MYSQL_DB")

if not all([MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DB]):
    raise RuntimeError(
        "MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT and MYSQL_DB must be set"
    )

# Как можно скачать сертификат для подключения к MySQL
# mkdir ~/.mysql
# curl -o ~/.mysql/root.crt https://storage.yandexcloud.net/cloud-certs/CA.pem
ssl_ca_path = os.path.expanduser("~/.mysql/root.crt")
assert os.path.isfile(ssl_ca_path), "Не найден сертификат для подключения к MySQL"

engine = create_engine(
    f"mysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?ssl_ca={ssl_ca_path}",
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Разогреваем пул, чтобы не было задержек при первом подключении
with engine.connect() as connection:
    pass

"""Database connection helpers."""
from __future__ import annotations

import os
from typing import Any

import mysql.connector


def get_connection() -> mysql.connector.connection.MySQLConnection:
    """Return a connection to the MySQL database.

    Connection parameters are taken from the environment variables
    ``DB_HOST``, ``DB_PORT``, ``DB_USER``, ``DB_PASSWORD`` and ``DB_NAME``.
    """
    config: dict[str, Any] = {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "database": os.environ.get("DB_NAME"),
        "charset": "utf8mb4",
        "use_unicode": True,
        "autocommit": True,
    }
    return mysql.connector.connect(**config)

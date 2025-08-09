"""SQLAlchemy models for database tables."""
from __future__ import annotations
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func


Base = declarative_base()


class User(Base):
    """Telegram user interacting with the bot."""

    __tablename__ = "users"

    # Telegram identifier of the user
    telegram_id = Column(BigInteger, primary_key=True)

    # Optional Telegram username
    telegram_login = Column(String(32), nullable=True)

    # Account balance
    balance = Column(Numeric(10, 2), nullable=False, default=0.00)

    # Registration timestamp
    registered_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class TranscriptionHistory(Base):
    """History of transcription requests made by users."""

    __tablename__ = "transcription_history"

    __table_args__ = (
        Index("idx_transcription_history_telegram_id", "telegram_id"),
    )

    # Identifier of transcription request
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Telegram user who made the request
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)

    # Processing status of the request
    status = Column(String(32), nullable=False)

    # Path to the audio file in S3
    audio_s3_path = Column(Text, nullable=False)

    # Duration of the audio in seconds
    duration_seconds = Column(Integer, nullable=True)

    # Path to the transcription result in S3
    result_s3_path = Column(Text, nullable=True)

    # Timestamp when the request was created
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

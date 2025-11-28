"""SQLAlchemy models for database tables."""
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
    balance = Column(Numeric(10, 2), nullable=False, default=250.00)

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

    # Raw recognition result returned by SpeechKit
    result_json = Column(Text, nullable=True)

    # Duration of the audio in seconds
    duration_seconds = Column(Integer, nullable=True)

    # Cost of recognition in rubles
    price_rub = Column(Numeric(10, 2), nullable=True)

    # Path to the transcription result in S3
    result_s3_path = Column(Text, nullable=True)

    # Identifier of Yandex Cloud operation
    operation_id = Column(String(128), nullable=True)

    # Identifier of the Telegram message with task status
    message_id = Column(Integer, nullable=True)

    # Telegram chat where the status message was sent
    chat_id = Column(BigInteger, nullable=True)

    # Timestamp when the request was created
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class Payment(Base):
    """Payments processed via Tinkoff acquiring."""

    __tablename__ = "payments"

    __table_args__ = (
        Index("idx_payments_telegram_id", "telegram_id"),
    )

    # Identifier of the payment record
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Telegram user who initiated the payment
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)

    # Identifier of the Telegram message with payment info
    message_id = Column(Integer, nullable=True)

    # Merchant order identifier
    order_id = Column(String(64), nullable=False, unique=True)

    # Identifier returned by Tinkoff
    payment_id = Column(BigInteger, nullable=False, unique=True)

    # Payment amount in rubles
    amount = Column(Numeric(10, 2), nullable=False)

    # Current payment status
    status = Column(String(32), nullable=False)

    # URL for completing the payment
    payment_url = Column(Text, nullable=False)

    # Optional description for the payment
    description = Column(String(255), nullable=False)

    # Raw tinkoff response for debugging
    tinkoff_response = Column(Text, nullable=False)

    # Timestamp when the payment was created
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

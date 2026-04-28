"""SQLAlchemy models for database tables."""
from sqlalchemy import (
    Column,
    Index,
    ForeignKeyConstraint,
    UniqueConstraint,
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from decimal import Decimal


Base = declarative_base()

PLATFORM_TELEGRAM = "telegram"
PLATFORM_MAX = "max"


class User(Base):
    """User interacting with the bot (Telegram or Max)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Platform user identifier (Telegram user ID or Max user ID)
    user_id = Column(BigInteger, nullable=False)

    # Platform: "telegram" or "max"
    user_platform = Column(String(16), nullable=False)

    # Account balance
    balance = Column(Numeric(10, 2), nullable=False, default=Decimal("50.00"))

    # Cumulative amount topped up across all confirmed payments (maintained by DB trigger)
    total_topped_up = Column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))

    # Registration timestamp
    registered_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint("user_id", "user_platform"),
    )


class Transcription(Base):
    """History of transcription requests made by users."""

    __tablename__ = "transcriptions"

    # Identifier of transcription request
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Platform user identifier
    user_id = Column(BigInteger, nullable=False)

    # Platform: "telegram" or "max"
    user_platform = Column(String(16), nullable=False)

    # Processing status of the request
    status = Column(String(32), nullable=False)

    # Path to the audio file in S3
    audio_s3_path = Column(Text, nullable=False)

    # Duration of the audio in seconds
    duration_seconds = Column(Integer, nullable=True)

    # Estimated cost shown to and charged from the user, in rubles
    price_for_user = Column(Numeric(10, 2), nullable=True)

    # Actual cost billed by the provider, in rubles
    actual_price = Column(Numeric(10, 2), nullable=True)

    # Path to the transcription result in S3
    result_s3_path = Column(Text, nullable=True)

    # Transcription provider used: "speechkit" or "replicate"
    provider = Column(String(16), nullable=True)

    # Model used for transcription
    model = Column(String(64), nullable=True)

    # Raw recognition result returned by the provider
    result_json = Column(Text, nullable=True)

    # Token counts for transcribed text by encoding
    llm_tokens_by_encoding = Column(JSON, nullable=True)

    # Identifier of the transcription operation returned by the provider
    operation_id = Column(String(64), nullable=True)

    # Identifier of the status message (string to support both Telegram int IDs and Max string IDs)
    message_id = Column(String(64), nullable=True)

    # User rating of the transcription quality (1–5 stars)
    rating = Column(Integer, nullable=True)

    # Optional free-text feedback left after a bad rating (1–3 stars)
    rating_comment = Column(Text, nullable=True)

    # Timestamp when the task was created and sent to the user for approval (before execution)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    # Timestamp when the transcription operation was started
    started_at = Column(DateTime, nullable=True)

    # Timestamp when the transcription operation finished
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "user_platform"],
            ["users.user_id", "users.user_platform"],
        ),
        Index("idx_transcriptions_status", "status"),
        Index("idx_transcriptions_user_recent", "user_id", "user_platform", "id"),
    )


class Refinement(Base):
    """Text refinement requests (summarization, improvement) for transcriptions."""

    __tablename__ = "refinements"

    # Identifier of refinement request
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Transcription this refinement was generated for
    transcription_id = Column(Integer, nullable=False)

    # Platform user identifier
    user_id = Column(BigInteger, nullable=False)

    # Platform: "telegram" or "max"
    user_platform = Column(String(16), nullable=False)

    # Identifier of the status message (string to support both Telegram int IDs and Max string IDs)
    message_id = Column(String(64), nullable=True)

    # Processing status: "pending" → "running" → "completed" / "failed"
    status = Column(String(32), nullable=False)

    # Replicate prediction ID (set when status becomes "running")
    operation_id = Column(String(64), nullable=True)

    # Task type: "summarize" or "improve"
    task_type = Column(String(16), nullable=False, server_default="summarize")

    # Result text produced by the LLM
    result_text = Column(Text, nullable=True)

    # LLM model used
    llm_model = Column(String(64), nullable=True)

    # Timestamp when the refinement was requested
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    # Timestamp when the refinement finished (completed or failed)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "user_platform"],
            ["users.user_id", "users.user_platform"],
        ),
        ForeignKeyConstraint(
            ["transcription_id"],
            ["transcriptions.id"],
        ),
        Index("idx_refinements_status", "status"),
        Index("idx_refinements_transcription_task", "transcription_id", "task_type"),
        Index("idx_refinements_user", "user_id", "user_platform"),
    )


class Payment(Base):
    """Payments processed via Tinkoff acquiring."""

    __tablename__ = "payments"

    # Identifier of the payment record
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Platform user identifier
    user_id = Column(BigInteger, nullable=False)

    # Platform: "telegram" or "max"
    user_platform = Column(String(16), nullable=False)

    # Identifier of the message with payment info (string to support both platforms)
    message_id = Column(String(64), nullable=True)

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

    # Next scheduled polling time
    next_check_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    # Timestamp when the payment was created
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "user_platform"],
            ["users.user_id", "users.user_platform"],
        ),
        Index("idx_payments_status_check", "status", "next_check_at"),
        Index("idx_payments_user_recent", "user_id", "user_platform", "id"),
    )

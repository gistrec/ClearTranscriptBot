from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    # Internal identifier
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Telegram user ID
    tg_id = Column(Integer, unique=True, nullable=False, index=True)

    # User name from Telegram profile
    name = Column(String(127), nullable=True)

    # When the user first interacted with the bot
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    transcripts = relationship("Transcript", back_populates="user")


class Transcript(Base):
    __tablename__ = "transcripts"

    # Transcript identifier
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Owner user id
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Path to the transcript file
    file_path = Column(String(255), nullable=False)

    # When the transcript was created
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="transcripts")

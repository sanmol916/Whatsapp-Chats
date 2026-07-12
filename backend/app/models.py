"""SQLAlchemy ORM models.

Schema overview:
  UploadJob   -> one per uploaded zip; tracks streaming/processing progress.
  Chat        -> one conversation (1:1 or group) found inside an export.
  Participant -> a person in a chat (name + phone number).
  Message     -> a single line/message in a chat.
  Media       -> a media file extracted from the zip, linked to a message.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UploadJob(Base):
    __tablename__ = "upload_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))
    # status: uploading -> uploaded -> processing -> done | error
    status: Mapped[str] = mapped_column(String(32), default="uploading", index=True)
    bytes_received: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100 for processing phase
    stage: Mapped[str] = mapped_column(String(64), default="")   # human readable current step
    error: Mapped[str] = mapped_column(Text, default="")
    chats_found: Mapped[int] = mapped_column(Integer, default=0)
    messages_found: Mapped[int] = mapped_column(Integer, default=0)
    media_found: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(512), default="Unknown chat")
    # For 1:1 chats we surface the primary contact's number here for convenience.
    phone_number: Mapped[str] = mapped_column(String(64), default="")
    is_group: Mapped[bool] = mapped_column(Integer, default=0)
    source_txt: Mapped[str] = mapped_column(String(1024), default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    media_count: Mapped[int] = mapped_column(Integer, default=0)
    first_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_message_preview: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    phone_number: Mapped[str] = mapped_column(String(64), default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    chat: Mapped["Chat"] = relationship(back_populates="participants")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # order within the chat
    sender_name: Mapped[str] = mapped_column(String(512), default="")
    sender_number: Mapped[str] = mapped_column(String(64), default="")
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # message_type: text | media | system
    message_type: Mapped[str] = mapped_column(String(16), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    media_id: Mapped[int | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )

    chat: Mapped["Chat"] = relationship(back_populates="messages")
    media: Mapped["Media | None"] = relationship(foreign_keys=[media_id])


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024))
    media_type: Mapped[str] = mapped_column(String(16), default="document", index=True)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


Index("ix_messages_chat_seq", Message.chat_id, Message.seq)

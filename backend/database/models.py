"""
SQLAlchemy ORM Models for Uzbek Receipt Parser
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime,
    Float, Integer, Numeric, String, Text, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


class Transaction(Base):
    """Model for financial transactions parsed from receipts"""
    __tablename__ = 'transactions'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    # Raw Data
    raw_message = Column(Text, nullable=False)
    source_type = Column(String(20), nullable=False)
    source_chat_id = Column(BigInteger, nullable=False)
    source_message_id = Column(BigInteger)
    
    # Parsed Transaction Data
    transaction_date = Column(DateTime(timezone=False), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default='UZS', nullable=False)
    card_last_4 = Column(String(4))
    operator_raw = Column(Text)
    application_mapped = Column(String(100))
    transaction_type = Column(String(20), nullable=False)
    balance_after = Column(Numeric(18, 2))

    # Receiver fields (for P2P transfers)
    receiver_name = Column(String(255))
    receiver_card = Column(String(4))

    # Metadata
    parsed_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    is_gpt_parsed = Column(Boolean, default=False)
    parsing_confidence = Column(Float)
    parsing_method = Column(String(20))
    is_p2p = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("source_type IN ('MANUAL', 'AUTO')", name='check_source_type'),
        CheckConstraint(
            "transaction_type IN ('DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL')", 
            name='check_transaction_type'
        ),
        CheckConstraint(
            "parsing_confidence >= 0 AND parsing_confidence <= 1", 
            name='check_confidence_range'
        ),
        CheckConstraint(
            "parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'GPT')",
            name='check_parsing_method'
        ),
        UniqueConstraint('source_chat_id', 'source_message_id', name='uq_transactions_source_msg'),
        Index('idx_transactions_date', 'transaction_date', postgresql_using='btree'),
        Index('idx_transactions_created', 'created_at', postgresql_using='btree'),
        Index('idx_transactions_card', 'card_last_4'),
        Index('idx_transactions_app', 'application_mapped'),
        Index('idx_transactions_operator', 'operator_raw'),
        Index('idx_transactions_amount', 'amount'),
        Index('idx_transactions_parsing', 'parsing_method', 'parsing_confidence'),
        Index('idx_transactions_source', 'source_type', 'source_chat_id'),
        Index('idx_transactions_parsed_at', 'parsed_at'),
    )
    
    def __repr__(self):
        return f"<Transaction(id={self.id}, date={self.transaction_date}, amount={self.amount} {self.currency})>"


class Check(Base):
    """Model for checks table from receipt_parser_dump.sql"""
    __tablename__ = 'checks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    
    # Transaction Details
    datetime = Column(DateTime(timezone=False), nullable=False)
    weekday = Column(String(2), nullable=False)
    date_display = Column(String(10), nullable=False)
    time_display = Column(String(5), nullable=False)
    
    operator = Column(String(255), nullable=False)
    app = Column(String(100))
    amount = Column(Numeric(15, 2), nullable=False)
    balance = Column(Numeric(15, 2))
    card_last4 = Column(String(4), nullable=False)
    
    is_p2p = Column(Boolean, default=False)
    transaction_type = Column(String(50), nullable=False)
    currency = Column(String(10), default='UZS', nullable=False)
    source = Column(String(20), nullable=False)
    
    # Raw data and metadata
    raw_text = Column(Text)
    added_via = Column(String(20), default='manual')
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer)
    
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())
    
    metadata_json = Column('metadata', Text)  # JSONB in original, using Text for simplicity
    source_chat_id = Column(Text)
    source_message_id = Column(Text)
    notify_message_id = Column(Text)
    fingerprint = Column(Text)
    source_bot_username = Column(Text)
    source_bot_title = Column(Text)
    source_app = Column(Text)
    
    __table_args__ = (
        Index('idx_checks_datetime', 'datetime', postgresql_using='btree'),
        Index('idx_checks_card', 'card_last4'),
        Index('idx_checks_operator', 'operator'),
        Index('idx_checks_app', 'app'),
        Index('idx_checks_source', 'source'),
        Index('idx_checks_check_id', 'check_id'),
    )
    
    def __repr__(self):
        return f"<Check(id={self.id}, date={self.datetime}, operator={self.operator}, amount={self.amount} {self.currency})>"


class ReceiptProcessingTask(Base):
    """Persistent tracking of receipt processing tasks (Telegram messages)."""
    __tablename__ = 'receipt_processing_tasks'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False)  # queued | processing | done | failed
    transaction_id = Column(BigInteger)  # References transactions.id
    error = Column(Text)
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('chat_id', 'message_id', name='uq_receipt_tasks_chat_msg'),
        Index('idx_receipt_tasks_status', 'status'),
        Index('idx_receipt_tasks_chat_msg', 'chat_id', 'message_id'),
    )

    def __repr__(self):
        return f"<ReceiptProcessingTask(task_id={self.task_id}, chat={self.chat_id}, msg={self.message_id}, status={self.status})>"


class MonitoredBotChat(Base):
    """Stores per-bot monitoring state for TDLib auto-processor."""

    __tablename__ = 'monitored_bot_chats'

    chat_id = Column(BigInteger, primary_key=True)
    enabled = Column(Boolean, nullable=False, server_default='true')
    last_processed_message_id = Column(BigInteger, nullable=False, server_default='0')
    last_error = Column(Text)

    # Group support and filtering
    chat_type = Column(String(50), nullable=False, server_default='private')
    filter_mode = Column(String(20), nullable=False, server_default='all')  # 'all', 'whitelist', 'blacklist'
    filter_keywords = Column(Text, nullable=True)  # JSON array: ["чек", "квитанция"]
    chat_title = Column(String(255), nullable=True)  # Cached title from TDLib

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<MonitoredBotChat(chat_id={self.chat_id}, enabled={self.enabled}, last_id={self.last_processed_message_id})>"


class OperatorMapping(Base):
    """Model for operator name to application mapping rules"""
    __tablename__ = 'operator_mappings'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern = Column(String(200), nullable=False, unique=True)
    app_name = Column(String(100), nullable=False)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_operator_mappings_pattern', 'pattern'),
        Index('idx_operator_mappings_priority', 'priority', postgresql_using='btree'),
    )
    
    def __repr__(self):
        return f"<OperatorMapping(pattern='{self.pattern}', app='{self.app_name}')>"


class ParsingLog(Base):
    """Model for tracking parsing attempts and debugging"""
    __tablename__ = 'parsing_logs'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_message = Column(Text, nullable=False)
    parsing_method = Column(String(20))
    success = Column(Boolean, nullable=False)
    error_message = Column(Text)
    processing_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_parsing_logs_failures', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ParsingLog(id={self.id}, success={self.success}, method={self.parsing_method})>"


class HourlyReport(Base):
    """Model for storing generated hourly analytics reports"""
    __tablename__ = 'hourly_reports'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    report_hour = Column(DateTime(timezone=True), nullable=False, unique=True)
    transaction_count = Column(Integer, nullable=False)
    total_volume_uzs = Column(Numeric(18, 2))
    top_application = Column(String(100))
    top_application_count = Column(Integer)
    gpt_insight = Column(Text)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<HourlyReport(hour={self.report_hour}, transactions={self.transaction_count})>"


class OperatorReference(Base):
    """Model for operator/seller reference dictionary"""
    __tablename__ = 'operator_reference'

    id = Column(Integer, primary_key=True, autoincrement=True)
    operator_name = Column(String(500), nullable=False)
    application_name = Column(String(200), nullable=False)
    # Explicit server_default to keep DB schema aligned with business default
    is_p2p = Column(Boolean, default=False, server_default='false')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_operator_ref_operator', 'operator_name'),
        Index('idx_operator_ref_app', 'application_name'),
        Index('idx_operator_ref_active', 'is_active'),
        Index('idx_operator_ref_p2p', 'is_p2p'),
        {'extend_existing': True}
    )

    def __repr__(self):
        return f"<OperatorReference(operator='{self.operator_name}', app='{self.application_name}', p2p={self.is_p2p})>"


class HiddenBotChat(Base):
    """Model for storing hidden bot chats (TDLib client)"""
    __tablename__ = 'hidden_bot_chats'

    chat_id = Column(BigInteger, primary_key=True)
    title_snapshot = Column(String(255))
    hidden_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<HiddenBotChat(chat_id={self.chat_id})>"


class AutomationTask(Base):
    """Persistent automation analysis tasks."""
    __tablename__ = 'automation_tasks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(20), nullable=False, default='pending')  # pending | processing | completed | failed
    progress_json = Column(Text)
    result_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomationSuggestion(Base):
    """AI suggestions linked to automation tasks."""
    __tablename__ = 'automation_suggestions'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    transaction_id = Column(BigInteger, nullable=False, index=True)
    suggested_application = Column(String(200), nullable=False)
    confidence = Column(Float, nullable=False)
    is_p2p = Column(Boolean, default=False)
    status = Column(String(20), default='pending')  # pending | approved | rejected
    reasoning = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

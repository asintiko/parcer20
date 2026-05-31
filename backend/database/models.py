"""
SQLAlchemy ORM Models for Uzbek Receipt Parser
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime,
    Float, Integer, JSON, Numeric, String, Text, Index, UniqueConstraint, Uuid,
    text as sql_text,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


class Transaction(Base):
    """Model for financial transactions parsed from receipts"""
    __tablename__ = 'transactions'
    
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    uuid = Column(Uuid(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
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
    receiver_card = Column(String(32))

    # Metadata
    parsed_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    is_gpt_parsed = Column(Boolean, default=False)
    parsing_confidence = Column(Float)
    parsing_method = Column(String(20))
    is_p2p = Column(Boolean, default=False)
    
    # Fingerprint for duplicate detection (SHA256 of amount|date|card|operator|type).
    # Partial unique index lives in migration 007 + __table_args__ below — keeps DB
    # in sync with ORM-managed Base.metadata.create_all() in tests.
    fingerprint = Column(String(64))

    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("source_type IN ('MANUAL', 'AUTO', 'SMS')", name='check_source_type'),
        CheckConstraint(
            "transaction_type IN ('DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL')", 
            name='check_transaction_type'
        ),
        CheckConstraint(
            "parsing_confidence >= 0 AND parsing_confidence <= 1", 
            name='check_confidence_range'
        ),
        CheckConstraint(
            "parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'REGEX_TRANSFER', 'GPT', 'GPT_VISION')",
            name='check_parsing_method'
        ),
        UniqueConstraint('source_chat_id', 'source_message_id', name='uq_transactions_source_msg'),
        Index('idx_transactions_date', 'transaction_date', postgresql_using='btree'),
        Index('idx_transactions_created', 'created_at', postgresql_using='btree'),
        Index(
            'idx_transactions_card',
            'card_last_4',
            postgresql_where=sql_text('card_last_4 IS NOT NULL'),
        ),
        Index(
            'idx_transactions_app',
            'application_mapped',
            postgresql_where=sql_text('application_mapped IS NOT NULL'),
        ),
        Index('idx_transactions_operator', 'operator_raw'),
        Index('idx_transactions_amount', 'amount'),
        Index('idx_transactions_parsing', 'parsing_method', 'parsing_confidence'),
        Index('idx_transactions_source', 'source_type', 'source_chat_id'),
        # idx_transactions_source_msg removed: duplicate of uq_transactions_source_msg.
        Index('idx_transactions_updated_id', 'updated_at', 'id'),
        # Partial UNIQUE on fingerprint — closes the dedup race condition.
        # Mirrors migration 007_unique_fingerprint.sql.
        Index(
            'uq_transactions_fingerprint',
            'fingerprint',
            unique=True,
            postgresql_where=sql_text('fingerprint IS NOT NULL'),
        ),
        Index(
            'idx_transactions_raw_message_trgm',
            'raw_message',
            postgresql_using='gin',
            postgresql_ops={'raw_message': 'gin_trgm_ops'},
        ),
        Index('idx_transactions_parsed_at', 'parsed_at'),
    )
    
    def __repr__(self):
        return f"<Transaction(id={self.id}, date={self.transaction_date}, amount={self.amount} {self.currency})>"


class Check(Base):
    """Model for checks table from receipt_parser_dump.sql"""
    __tablename__ = 'checks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(Uuid(as_uuid=True), default=uuid.uuid4)
    
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

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False)  # queued | processing | done | failed
    transaction_id = Column(BigInteger)  # References transactions.id
    error = Column(Text)
    raw_message = Column(Text, nullable=True)  # Source message text (stored for failed tasks)
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
    last_history_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_realtime_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_receipt_candidate_at = Column(DateTime(timezone=True), nullable=True)
    last_sync_issue_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_monitored_bot_chats_enabled', 'enabled'),
        Index('idx_monitored_bot_chats_sync_health', 'last_history_sync_at', 'last_realtime_seen_at'),
    )

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
    
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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


class TgChatMessage(Base):
    """Persisted Telegram chat history messages loaded from TDLib."""
    __tablename__ = "tg_chat_messages"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    message_date = Column(DateTime(timezone=False), nullable=True)
    is_outgoing = Column(Boolean, nullable=False, default=False, server_default="false")
    sender_id = Column(BigInteger, nullable=True)
    text = Column(Text, nullable=True)
    raw_json = Column(Text, nullable=False)
    receipt_transaction_id = Column(BigInteger, nullable=True)
    content_type = Column(String(40), nullable=True)
    media_kind = Column(String(40), nullable=True)
    looks_like_receipt = Column(Boolean, nullable=False, default=False, server_default="false")
    processing_status = Column(String(30), nullable=True)
    processing_error_code = Column(String(80), nullable=True)
    processing_error_text = Column(Text, nullable=True)
    duplicate_status = Column(String(30), nullable=True)
    message_hash = Column(String(128), nullable=True)
    source_chat_title_snapshot = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_tg_chat_messages_chat_message"),
        # idx_tg_chat_messages_chat_msg removed: duplicate of uq_tg_chat_messages_chat_message.
        Index("idx_tg_chat_messages_chat_date", "chat_id", "message_date"),
        Index("idx_tg_chat_messages_updated", "updated_at"),
        Index("idx_tg_chat_messages_receipt_tx", "receipt_transaction_id"),
        Index("idx_tg_chat_messages_receipt_like", "looks_like_receipt"),
        Index(
            "uq_tg_chat_messages_message_hash",
            "message_hash",
            unique=True,
            postgresql_where=sql_text("message_hash IS NOT NULL"),
        ),
        Index("idx_tg_chat_messages_processing_status", "processing_status"),
        Index("idx_tg_chat_messages_duplicate_status", "duplicate_status"),
        Index("idx_tg_chat_messages_message_hash", "message_hash"),
    )

    def __repr__(self):
        return f"<TgChatMessage(chat_id={self.chat_id}, message_id={self.message_id})>"


class TgHistoryCursor(Base):
    """Progress cursor/status for background full history loading per chat."""
    __tablename__ = "tg_history_cursors"

    chat_id = Column(BigInteger, primary_key=True)
    status = Column(String(20), nullable=False, default="idle", server_default="idle")
    cursor_message_id = Column(BigInteger, nullable=False, default=0, server_default="0")
    loaded_count = Column(BigInteger, nullable=False, default=0, server_default="0")
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    last_batch_at = Column(DateTime(timezone=True), nullable=True)
    lag_messages = Column(BigInteger, nullable=False, default=0, server_default="0")
    lag_seconds = Column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_tg_history_cursors_status", "status"),
        Index("idx_tg_history_cursors_updated", "updated_at"),
        Index("idx_tg_history_cursors_lag", "lag_messages", "lag_seconds"),
    )

    def __repr__(self):
        return f"<TgHistoryCursor(chat_id={self.chat_id}, status={self.status}, cursor={self.cursor_message_id})>"


class AutomationTask(Base):
    """Persistent automation analysis tasks."""
    __tablename__ = 'automation_tasks'

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type = Column(String(30), nullable=True, server_default="mapping")  # mapping | verification | reconciliation
    status = Column(String(20), nullable=False, default='pending')  # pending | processing | completed | failed
    version = Column(Integer, nullable=False, default=1, server_default="1")
    progress_json = Column(Text)
    result_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomationSuggestion(Base):
    """AI suggestions linked to automation tasks."""
    __tablename__ = 'automation_suggestions'

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    transaction_id = Column(BigInteger, nullable=False, index=True)
    suggested_application = Column(String(200), nullable=False)
    confidence = Column(Float, nullable=False)
    is_p2p = Column(Boolean, default=False)
    status = Column(String(20), default='pending')  # pending | approved | rejected
    reasoning = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VerificationSuggestion(Base):
    """AI verification suggestions for field-level corrections."""
    __tablename__ = 'verification_suggestions'

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    transaction_id = Column(BigInteger, nullable=False, index=True)
    field_name = Column(String(50), nullable=False)  # e.g. 'amount', 'transaction_date'
    current_value = Column(Text)
    suggested_value = Column(Text)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    status = Column(String(20), default='pending')  # pending | approved | rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_verification_sug_task', 'task_id'),
        Index('idx_verification_sug_tx', 'transaction_id'),
        Index('idx_verification_sug_status', 'status'),
    )

    def __repr__(self):
        return f"<VerificationSuggestion(tx={self.transaction_id}, field={self.field_name}, conf={self.confidence})>"


class ReconciliationSuggestion(Base):
    """Reconciliation suggestions persisted for review/apply flows."""
    __tablename__ = "reconciliation_suggestions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    transaction_id = Column(BigInteger, nullable=True, index=True)
    category = Column(String(30), nullable=False)  # MATCHED|MISSING_IN_DB|FAILED_PARSE|ORPHANED_IN_DB
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="check_reconcile_suggestion_status"),
        Index("idx_reconcile_sug_task", "task_id"),
        Index("idx_reconcile_sug_chat_msg", "chat_id", "message_id"),
        Index("idx_reconcile_sug_category", "category"),
    )

    def __repr__(self):
        return f"<ReconciliationSuggestion(task={self.task_id}, chat={self.chat_id}, msg={self.message_id})>"


class DuplicateSuggestion(Base):
    """Duplicate merge suggestions produced by automation agents."""
    __tablename__ = "duplicate_suggestions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    primary_transaction_id = Column(BigInteger, nullable=False, index=True)
    duplicate_transaction_id = Column(BigInteger, nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    reasoning = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="check_duplicate_suggestion_status"),
        UniqueConstraint("primary_transaction_id", "duplicate_transaction_id", name="uq_duplicate_pair"),
        Index("idx_duplicate_sug_task", "task_id"),
        Index("idx_duplicate_sug_status", "status"),
    )

    def __repr__(self):
        return f"<DuplicateSuggestion(primary={self.primary_transaction_id}, dup={self.duplicate_transaction_id})>"


class AutomationAgentConfig(Base):
    """Persistent configuration per automation agent."""
    __tablename__ = "automation_agent_configs"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_name = Column(String(80), nullable=False, unique=True)
    config_json = Column(Text, nullable=False, default="{}", server_default="{}")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    updated_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_automation_agent_cfg_name", "agent_name"),
        Index("idx_automation_agent_cfg_active", "is_active"),
    )

    def __repr__(self):
        return f"<AutomationAgentConfig(agent={self.agent_name}, active={self.is_active})>"


class AgentThread(Base):
    """Persistent AI-agent thread per authenticated user."""
    __tablename__ = "agent_threads"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_user_id = Column(BigInteger, nullable=False, index=True)
    title = Column(String(255), nullable=False, default="Новый диалог", server_default="Новый диалог")
    context_json = Column(Text, nullable=False, default="{}", server_default="{}")
    last_message_preview = Column(String(500), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by_user_id = Column(BigInteger, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id = Column(BigInteger, nullable=True)
    purge_after = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_agent_threads_user_updated", "created_by_user_id", "updated_at"),
        Index("idx_agent_threads_archived", "created_by_user_id", "archived_at"),
        Index("idx_agent_threads_deleted", "created_by_user_id", "deleted_at", "purge_after"),
    )

    def __repr__(self):
        return f"<AgentThread(id={self.id}, user={self.created_by_user_id})>"


class AgentMessage(Base):
    """Thread messages and structured cards emitted by the AI agent."""
    __tablename__ = "agent_messages"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    run_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | system | tool
    message_type = Column(String(30), nullable=False, default="text", server_default="text")
    content_json = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="check_agent_message_role"),
        CheckConstraint(
            "message_type IN ('text', 'tool_run', 'report', 'confirmation', 'warning', 'navigation')",
            name="check_agent_message_type",
        ),
        Index("idx_agent_messages_thread_created", "thread_id", "created_at"),
    )

    def __repr__(self):
        return f"<AgentMessage(thread={self.thread_id}, role={self.role}, type={self.message_type})>"


class AgentRun(Base):
    """Long-running agent orchestration runs with structured progress/result state."""
    __tablename__ = "agent_runs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    created_by_user_id = Column(BigInteger, nullable=False, index=True)
    status = Column(String(40), nullable=False, default="queued", server_default="queued")
    tool_name = Column(String(80), nullable=True)
    progress_json = Column(Text, nullable=False, default="{}", server_default="{}")
    result_json = Column(Text, nullable=True)
    error_text = Column(Text, nullable=True)
    requires_confirmation = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'awaiting_confirmation', 'completed', 'failed', 'cancelled')",
            name="check_agent_run_status",
        ),
        Index("idx_agent_runs_thread_updated", "thread_id", "updated_at"),
        Index("idx_agent_runs_user_created", "created_by_user_id", "created_at"),
    )

    def __repr__(self):
        return f"<AgentRun(id={self.id}, thread={self.thread_id}, status={self.status})>"


class AgentRunEvent(Base):
    """Micro-events for live agent execution timeline."""
    __tablename__ = "agent_run_events"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    label = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    payload_json = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('planning_started', 'tool_selected', 'tool_started', 'tool_progress', 'tool_finished', 'awaiting_confirmation', 'completed', 'failed')",
            name="check_agent_run_event_type",
        ),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="check_agent_run_event_status"),
        Index("idx_agent_run_events_run_created", "run_id", "created_at"),
    )

    def __repr__(self):
        return f"<AgentRunEvent(run={self.run_id}, type={self.event_type}, status={self.status})>"


class AgentReport(Base):
    """Generated agent reports, both personal and team-visible."""
    __tablename__ = "agent_reports"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_user_id = Column(BigInteger, nullable=False, index=True)
    thread_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    scope = Column(String(20), nullable=False, default="personal", server_default="personal")
    title = Column(String(255), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="ready", server_default="ready")
    summary_json = Column(Text, nullable=False, default="{}", server_default="{}")
    payload_json = Column(Text, nullable=False, default="{}", server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("scope IN ('personal', 'team')", name="check_agent_report_scope"),
        CheckConstraint("status IN ('draft', 'ready', 'published', 'archived')", name="check_agent_report_status"),
        Index("idx_agent_reports_scope_created", "scope", "created_at"),
    )

    def __repr__(self):
        return f"<AgentReport(id={self.id}, scope={self.scope}, title={self.title})>"


class AgentReportItem(Base):
    """Actionable report issues that can be claimed/released/reassigned by team members."""
    __tablename__ = "agent_report_items"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    issue_type = Column(String(80), nullable=False)
    severity = Column(String(20), nullable=False, default="medium", server_default="medium")
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="open", server_default="open")
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    suggested_action_json = Column(Text, nullable=False, default="{}", server_default="{}")
    assignee_user_id = Column(BigInteger, nullable=True, index=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="check_agent_report_item_severity"),
        CheckConstraint("status IN ('open', 'claimed', 'released', 'resolved')", name="check_agent_report_item_status"),
        Index("idx_agent_report_items_report_status", "report_id", "status"),
        Index("idx_agent_report_items_assignee_status", "assignee_user_id", "status"),
    )

    def __repr__(self):
        return f"<AgentReportItem(id={self.id}, report={self.report_id}, status={self.status})>"


class AgentNotification(Base):
    """In-app notifications for agent runs, reports, and team workflow."""
    __tablename__ = "agent_notifications"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(20), nullable=False, default="personal", server_default="personal")
    user_id = Column(BigInteger, nullable=True, index=True)
    report_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    report_item_id = Column(Uuid(as_uuid=True), nullable=True, index=True)
    type = Column(String(80), nullable=False)
    payload_json = Column(Text, nullable=False, default="{}", server_default="{}")
    is_read = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("scope IN ('personal', 'team')", name="check_agent_notification_scope"),
        Index("idx_agent_notifications_scope_created", "scope", "created_at"),
        Index("idx_agent_notifications_user_unread", "user_id", "is_read"),
    )

    def __repr__(self):
        return f"<AgentNotification(id={self.id}, scope={self.scope}, type={self.type})>"


class ReceiptProcessingIncident(Base):
    """Operational incidents for missing, failed, duplicate, or stale receipt flows."""
    __tablename__ = "receipt_processing_incidents"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(BigInteger, nullable=False, index=True)
    message_id = Column(BigInteger, nullable=True, index=True)
    transaction_id = Column(BigInteger, nullable=True, index=True)
    task_id = Column(BigInteger, nullable=True, index=True)
    incident_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="medium", server_default="medium")
    status = Column(String(20), nullable=False, default="open", server_default="open")
    reason_code = Column(String(80), nullable=True)
    reason_text = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=False, default="{}", server_default="{}")
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="check_receipt_incident_severity"),
        CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'ignored')", name="check_receipt_incident_status"),
        Index("idx_receipt_incidents_chat_message", "chat_id", "message_id"),
        Index("idx_receipt_incidents_status_seen", "status", "last_seen_at"),
        Index("idx_receipt_incidents_type_status", "incident_type", "status"),
    )

    def __repr__(self):
        return f"<ReceiptProcessingIncident(chat={self.chat_id}, message={self.message_id}, type={self.incident_type}, status={self.status})>"


class AccessScope(Base):
    """Password-based access scopes (years/date ranges + source permissions)."""
    __tablename__ = "access_scopes"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False, unique=True)
    password_hash = Column(String(256), nullable=False)
    salt = Column(String(64), nullable=False)

    # JSON string list, example: [2025, 2026]
    years_json = Column(Text, nullable=True)
    period_start = Column(DateTime(timezone=False), nullable=True)
    period_end = Column(DateTime(timezone=False), nullable=True)

    allow_transactions = Column(Boolean, nullable=False, default=True, server_default="true")
    allow_sources = Column(Boolean, nullable=False, default=False, server_default="false")
    auth_method = Column(String(20), nullable=False, default="otp", server_default="otp")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_access_scopes_active", "is_active"),
        Index("idx_access_scopes_period", "period_start", "period_end"),
        Index("idx_access_scopes_auth_method", "auth_method"),
    )

    def __repr__(self):
        return f"<AccessScope(id={self.id}, name={self.name}, active={self.is_active})>"


class AccessLockout(Base):
    """Tracks failed unlock attempts to throttle password guessing."""
    __tablename__ = "access_lockouts"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    lock_key = Column(String(190), nullable=False, unique=True)
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    blocked_until = Column(DateTime(timezone=False), nullable=True)
    last_failed_at = Column(DateTime(timezone=False), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_access_lockouts_key", "lock_key"),
        Index("idx_access_lockouts_blocked", "blocked_until"),
    )

    def __repr__(self):
        return f"<AccessLockout(key={self.lock_key}, failed={self.failed_attempts})>"


class AccessAuditLog(Base):
    """Audit trail for scoped access and restricted actions."""
    __tablename__ = "access_audit_logs"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    action = Column(String(80), nullable=False)
    success = Column(Boolean, nullable=False, default=False, server_default="false")
    scope_id = Column(BigInteger, nullable=True)
    user_id = Column(BigInteger, nullable=True)
    ip_address = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_access_audit_action", "action"),
        Index("idx_access_audit_created", "created_at"),
        Index("idx_access_audit_scope", "scope_id"),
    )

    def __repr__(self):
        return f"<AccessAuditLog(action={self.action}, success={self.success})>"


class DuplicateMergeLog(Base):
    """Audit trail for duplicate detection/merge decisions."""
    __tablename__ = "duplicate_merge_logs"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    fingerprint = Column(String(64), nullable=True)
    existing_transaction_id = Column(BigInteger, nullable=False)
    source_chat_id = Column(BigInteger, nullable=True)
    source_message_id = Column(BigInteger, nullable=True)
    merged = Column(Boolean, nullable=False, default=False, server_default="false")
    candidate_method = Column(String(32), nullable=True)
    candidate_confidence = Column(Float, nullable=True)
    existing_method = Column(String(32), nullable=True)
    existing_confidence = Column(Float, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_dup_merge_created", "created_at"),
        Index("idx_dup_merge_tx", "existing_transaction_id"),
        Index("idx_dup_merge_fp", "fingerprint"),
    )

    def __repr__(self):
        return f"<DuplicateMergeLog(tx={self.existing_transaction_id}, merged={self.merged})>"


class SyncDeletion(Base):
    """Tracks deletions per table so clients can mirror removals locally."""
    __tablename__ = "sync_deletions"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False)
    record_id = Column(BigInteger, nullable=False)
    deleted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_sync_deletions_table", "table_name"),
        Index("idx_sync_deletions_deleted", "deleted_at"),
        Index("idx_sync_deletions_table_record", "table_name", "record_id"),
        Index("idx_sync_deletions_table_deleted_id", "table_name", "deleted_at", "id"),
        Index("idx_sync_deletions_cleanup", "deleted_at", "id"),
    )

    def __repr__(self):
        return f"<SyncDeletion(table={self.table_name}, record_id={self.record_id})>"


class ChatPassword(Base):
    """Password lock for individual Telegram chats."""
    __tablename__ = "chat_passwords"

    chat_id = Column(BigInteger, primary_key=True)
    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    hash_method = Column(String(50), nullable=False, default="pbkdf2_sha256", server_default="pbkdf2_sha256")
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_chat_passwords_locked", "locked_until"),
    )

    def __repr__(self):
        return f"<ChatPassword(chat_id={self.chat_id})>"


class AppLaunchConfig(Base):
    """Single-row table storing desktop launch password configuration."""
    __tablename__ = "app_launch_config"

    id = Column(Integer, primary_key=True, default=1, server_default="1")
    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    hash_method = Column(String(50), nullable=False, default="pbkdf2_sha256", server_default="pbkdf2_sha256")
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by_tg_id = Column(BigInteger, nullable=True)

    def __repr__(self):
        return f"<AppLaunchConfig(id={self.id})>"


class SystemSettings(Base):
    """Single-row runtime security toggles."""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, default=1, server_default="1")
    otp_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    bot_control_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    totp_2fa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    launch_gate_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<SystemSettings(id={self.id})>"


class User(Base):
    """Application user with role-based access permissions."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    hash_method = Column(String(50), nullable=False, default="pbkdf2_sha256", server_default="pbkdf2_sha256")
    role = Column(String(20), nullable=False, default="operator", server_default="operator")
    display_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    allowed_tabs = Column(Text, nullable=False, default='["dashboard"]', server_default='["dashboard"]')
    allowed_folders = Column(Text, nullable=False, default="[]", server_default="[]")
    forbidden_periods = Column(Text, nullable=False, default="[]", server_default="[]")
    allowed_sources = Column(Text, nullable=False, default="[]", server_default="[]")
    can_toggle_sources = Column(Boolean, nullable=False, default=False, server_default="false")
    force_2fa = Column(Boolean, nullable=False, default=False, server_default="false")
    session_ttl_days = Column(Integer, nullable=False, default=7, server_default="7")

    # Telegram link
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username = Column(String(255), nullable=True)

    # TOTP 2FA
    totp_secret = Column(String(128), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    totp_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    backup_codes = Column(Text, nullable=True)

    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    permissions_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'operator')", name="check_user_role"),
        CheckConstraint("session_ttl_days >= 1 AND session_ttl_days <= 90", name="check_user_session_ttl_days"),
        Index("idx_users_role_active", "role", "is_active"),
    )

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role}, active={self.is_active})>"


class LockedPeriod(Base):
    """Date ranges blocked from viewing/exporting/sync."""
    __tablename__ = "locked_periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    reason = Column(String(500), nullable=True)
    locked_by_tg_id = Column(BigInteger, nullable=False)
    locked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    excluded_user_ids = Column(JSON, nullable=False, default=list, server_default="[]")

    __table_args__ = (
        CheckConstraint("date_from <= date_to", name="check_period_valid"),
        Index("idx_locked_periods_active", "is_active"),
        Index("idx_locked_periods_range", "date_from", "date_to"),
    )

    def __repr__(self):
        return f"<LockedPeriod(id={self.id}, from={self.date_from}, to={self.date_to}, active={self.is_active})>"


class AgentRoutine(Base):
    """User-defined scheduled agent task ('routine').

    A routine is a natural-language task the AI agent runs on a cron schedule
    (e.g. weekly reconciliation). The task is executed through the safe tool
    pipeline — never raw generated code.
    """
    __tablename__ = "agent_routines"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # The NL task the agent executes each run.
    task_prompt = Column(Text, nullable=False)
    # 5-field cron (min hour dom mon dow) in APP_TIMEZONE.
    cron = Column(String(120), nullable=False, default="0 12 * * 1", server_default="0 12 * * 1")
    # Preset action this routine maps to (safe primitive): reconcile | summary | custom.
    kind = Column(String(40), nullable=False, default="reconcile", server_default="reconcile")
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    deliver_to_channel = Column(Boolean, nullable=False, default=True, server_default="true")
    deliver_to_chat = Column(Boolean, nullable=False, default=True, server_default="true")
    config_json = Column(Text, nullable=False, default="{}", server_default="{}")
    # Schedule kind: recurring cron, or a one-shot fire at run_at.
    schedule_kind = Column(String(20), nullable=False, default="recurring", server_default="recurring")
    run_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(BigInteger, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)  # ok | error | running
    last_summary = Column(Text, nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('reconcile', 'summary', 'custom', 'receipt_audit')", name="check_agent_routine_kind"),
        CheckConstraint("last_status IS NULL OR last_status IN ('ok', 'error', 'running')", name="check_agent_routine_status"),
        CheckConstraint("schedule_kind IN ('recurring', 'once')", name="check_agent_routine_schedule_kind"),
        Index("idx_agent_routines_enabled", "enabled"),
    )

    def __repr__(self):
        return f"<AgentRoutine(id={self.id}, name={self.name}, cron={self.cron}, enabled={self.enabled})>"


class AgentRoutineRun(Base):
    """History of routine executions."""
    __tablename__ = "agent_routine_runs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    routine_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="running", server_default="running")
    trigger = Column(String(20), nullable=False, default="schedule", server_default="schedule")  # schedule | manual
    summary = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error_text = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'error')", name="check_agent_routine_run_status"),
        Index("idx_agent_routine_runs_routine_started", "routine_id", "started_at"),
    )

    def __repr__(self):
        return f"<AgentRoutineRun(routine={self.routine_id}, status={self.status})>"


class AgentChatCommand(Base):
    """Reusable quick-command (saved prompt template) for the agent chat palette.

    Operators pick a command in the chat input; the frontend sends the stored
    `prompt_template` to the agent (optionally pre-selecting `requested_tool`).
    """
    __tablename__ = "agent_chat_commands"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(120), nullable=False)
    icon = Column(String(40), nullable=True)
    prompt_template = Column(Text, nullable=False)
    requested_tool = Column(String(80), nullable=True)
    scope = Column(String(20), nullable=False, default="team", server_default="team")  # team | personal
    created_by_user_id = Column(BigInteger, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("scope IN ('team', 'personal')", name="check_agent_chat_command_scope"),
        Index("idx_agent_chat_commands_enabled_sort", "enabled", "sort_order"),
    )

    def __repr__(self):
        return f"<AgentChatCommand(id={self.id}, title={self.title}, scope={self.scope})>"

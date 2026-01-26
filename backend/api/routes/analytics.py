"""
Analytics API routes
Provides aggregated statistics and insights
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import os

from database.connection import get_db_session
from database.models import Transaction
from api.dependencies import get_current_user

router = APIRouter()


class TopAgentResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    transaction_count: int
    top_application: Optional[str]
    top_application_count: int
    top_application_volume: str
    total_volume: str
    insight: str


@router.get("/top-agent", response_model=TopAgentResponse)
async def get_top_agent(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Get 'Top Agent' statistics for the last hour
    Returns the most active application/operator by transaction count and volume
    """
    # Define time window (last hour)
    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    
    # Get transactions in last hour
    recent_transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= hour_ago
    ).all()
    
    transaction_count = len(recent_transactions)
    
    if transaction_count == 0:
        return TopAgentResponse(
            period_start=hour_ago,
            period_end=now,
            transaction_count=0,
            top_application=None,
            top_application_count=0,
            top_application_volume="0",
            total_volume="0",
            insight="No transactions in the last hour"
        )
    
    # Calculate total volume
    total_volume = sum(abs(float(t.amount)) for t in recent_transactions if t.currency == 'UZS')
    
    # Find top application by count
    app_counts = {}
    app_volumes = {}
    
    for t in recent_transactions:
        app = t.application_mapped or t.operator_raw or "Unknown"
        app_counts[app] = app_counts.get(app, 0) + 1
        if t.currency == 'UZS':
            app_volumes[app] = app_volumes.get(app, 0) + abs(float(t.amount))
    
    top_app = max(app_counts, key=app_counts.get)
    top_app_count = app_counts[top_app]
    top_app_volume = app_volumes.get(top_app, 0)
    
    # Generate insight (could use GPT here for more sophisticated analysis)
    percentage = (top_app_count / transaction_count) * 100
    
    insight = f"Most active: {top_app} with {top_app_count} transaction(s) ({percentage:.1f}% of total). "
    
    if top_app_volume > 0:
        volume_percentage = (top_app_volume / total_volume) * 100 if total_volume > 0 else 0
        insight += f"Volume: {top_app_volume:,.0f} UZS ({volume_percentage:.1f}% of total)."
    
    return TopAgentResponse(
        period_start=hour_ago,
        period_end=now,
        transaction_count=transaction_count,
        top_application=top_app,
        top_application_count=top_app_count,
        top_application_volume=f"{top_app_volume:,.2f}",
        total_volume=f"{total_volume:,.2f}",
        insight=insight
    )


@router.get("/summary")
async def get_summary(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Get overall system statistics
    """
    total_transactions = db.query(func.count(Transaction.id)).scalar()
    
    # Count by type
    debit_count = db.query(func.count(Transaction.id)).filter(
        Transaction.transaction_type == 'DEBIT'
    ).scalar()
    
    credit_count = db.query(func.count(Transaction.id)).filter(
        Transaction.transaction_type == 'CREDIT'
    ).scalar()
    
    # GPT usage
    gpt_parsed = db.query(func.count(Transaction.id)).filter(
        Transaction.is_gpt_parsed == True
    ).scalar()
    
    # Total volume (UZS only)
    total_volume = db.query(func.sum(func.abs(Transaction.amount))).filter(
        Transaction.currency == 'UZS'
    ).scalar() or 0
    
    # Average confidence
    avg_confidence = db.query(func.avg(Transaction.parsing_confidence)).filter(
        Transaction.parsing_confidence.isnot(None)
    ).scalar() or 0
    
    return {
        "total_transactions": total_transactions,
        "debit_count": debit_count,
        "credit_count": credit_count,
        "gpt_parsed_count": gpt_parsed,
        "gpt_usage_percentage": (gpt_parsed / total_transactions * 100) if total_transactions > 0 else 0,
        "total_volume_uzs": f"{float(total_volume):,.2f}",
        "average_confidence": round(float(avg_confidence), 3)
    }

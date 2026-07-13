"""Merchant Descriptions API.

A description is a free-text label bound to one or more *normalized operator keys*.
It is resolved at transaction read time, so it applies retroactively to every
transaction whose ``operator_raw`` normalizes to a linked key.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc as sa_desc, func
from sqlalchemy.orm import Session

from database.connection import get_db_session
from database.models import Description, OperatorDescriptionLink
from api.dependencies import require_tab_access
from services import description_service

router = APIRouter()
logger = logging.getLogger(__name__)


class DescriptionResponse(BaseModel):
    id: int
    text: str
    operator_keys: List[str] = []
    operator_count: int = 0
    sources: List[str] = []

    class Config:
        from_attributes = True


class DescriptionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[DescriptionResponse]


class DescriptionCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    operator_raws: List[str] = Field(default_factory=list)
    source: str = "manual"


class DescriptionUpdateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class OperatorLinkRequest(BaseModel):
    operator_raws: List[str] = Field(..., min_length=1)
    source: str = "manual"


def _serialize(db: Session, item: Description) -> DescriptionResponse:
    links = (
        db.query(OperatorDescriptionLink)
        .filter(OperatorDescriptionLink.description_id == item.id)
        .all()
    )
    return DescriptionResponse(
        id=int(item.id),
        text=item.text,
        operator_keys=sorted({link.operator_key for link in links}),
        operator_count=len(links),
        sources=sorted({link.source for link in links if link.source}),
    )


@router.get("", response_model=DescriptionListResponse)
@router.get("/", response_model=DescriptionListResponse, include_in_schema=False)
async def list_descriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None, description="Search in description text or operator key"),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    query = db.query(Description)
    if search:
        pattern = f"%{search}%"
        matched_ids = (
            db.query(OperatorDescriptionLink.description_id)
            .filter(OperatorDescriptionLink.operator_key.ilike(pattern))
        )
        query = query.filter(
            (Description.text.ilike(pattern)) | (Description.id.in_(matched_ids.scalar_subquery()))
        )

    total = query.count()
    offset = (page - 1) * page_size
    items = (
        query.order_by(sa_desc(Description.id))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return DescriptionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_serialize(db, item) for item in items],
    )


@router.post("", response_model=DescriptionResponse)
@router.post("/", response_model=DescriptionResponse, include_in_schema=False)
async def create_description(
    payload: DescriptionCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    try:
        user_id = (current_user or {}).get("user_id")
        new_desc = Description(text=payload.text.strip(), created_by_user_id=user_id)
        db.add(new_desc)
        db.commit()
        db.refresh(new_desc)

        if payload.operator_raws:
            description_service.link_operators(
                db,
                description_id=int(new_desc.id),
                operator_raws=payload.operator_raws,
                source=payload.source or "manual",
                user_id=user_id,
            )
            db.refresh(new_desc)
        else:
            description_service.invalidate_descriptions_cache()

        return _serialize(db, new_desc)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Error creating description")
        raise HTTPException(status_code=500, detail="Failed to create description")


@router.patch("/{description_id}", response_model=DescriptionResponse)
async def update_description(
    description_id: int,
    payload: DescriptionUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    try:
        item = db.query(Description).filter(Description.id == description_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Description not found")
        item.text = payload.text.strip()
        db.commit()
        db.refresh(item)
        description_service.invalidate_descriptions_cache()
        return _serialize(db, item)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Error updating description")
        raise HTTPException(status_code=500, detail="Failed to update description")


@router.delete("/{description_id}")
async def delete_description(
    description_id: int,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    try:
        item = db.query(Description).filter(Description.id == description_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Description not found")
        db.query(OperatorDescriptionLink).filter(
            OperatorDescriptionLink.description_id == description_id
        ).delete(synchronize_session=False)
        db.delete(item)
        db.commit()
        description_service.invalidate_descriptions_cache()
        return {"message": "Description deleted successfully", "deleted_id": int(description_id)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Error deleting description")
        raise HTTPException(status_code=500, detail="Failed to delete description")


@router.post("/{description_id}/operators", response_model=DescriptionResponse)
async def link_operators(
    description_id: int,
    payload: OperatorLinkRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    item = db.query(Description).filter(Description.id == description_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Description not found")
    description_service.link_operators(
        db,
        description_id=int(description_id),
        operator_raws=payload.operator_raws,
        source=payload.source or "manual",
        user_id=(current_user or {}).get("user_id"),
    )
    db.refresh(item)
    return _serialize(db, item)


@router.delete("/{description_id}/operators", response_model=DescriptionResponse)
async def unlink_operators(
    description_id: int,
    payload: OperatorLinkRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("reference")),
):
    item = db.query(Description).filter(Description.id == description_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Description not found")
    description_service.unlink_operators(
        db,
        description_id=int(description_id),
        operator_raws=payload.operator_raws,
    )
    refreshed = db.query(Description).filter(Description.id == description_id).first()
    if refreshed is None:
        return DescriptionResponse(id=int(description_id), text="", operator_keys=[], operator_count=0, sources=[])
    return _serialize(db, refreshed)

from typing import Any
"""首页运维指挥中心路由。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_session
from core.dependencies import get_current_user
from modules.dashboard.schemas import DashboardSummary
from modules.dashboard.service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["运维指挥中心"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user),
) -> Any:
    return await DashboardService.get_summary(db)

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from auth.deps import get_current_user
from db.models import Job, User
from db.session import get_db
from api.schemas import MeResponse

router = APIRouter()

@router.get("/api/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(select(func.count(Job.id)).where(Job.user_id == user.id)) or 0
    return MeResponse(user_id=user.id, email=user.email, name=user.name, job_count=count)

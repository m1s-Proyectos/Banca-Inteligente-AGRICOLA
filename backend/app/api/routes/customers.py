from fastapi import APIRouter

from app.db.session import DbSession
from app.schemas.dashboard import CustomerOut
from app.services.dashboard import list_customers

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
def get_customers(db: DbSession) -> list[CustomerOut]:
    return list_customers(db)


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import CustomerOut
from app.services.dashboard import list_customers

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
def get_customers(db: Session = Depends(get_db)) -> list[CustomerOut]:
    return list_customers(db)


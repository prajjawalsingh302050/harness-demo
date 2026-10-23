from fastapi import APIRouter, Depends

from app.api.deps import get_services
from app.schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, services=Depends(get_services)):
    return services.users.get_user(user_id)

from fastapi import APIRouter, Depends

from app.api.deps import get_services
from app.schemas import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthOut)
def health(services=Depends(get_services)):
    return services.health.check()

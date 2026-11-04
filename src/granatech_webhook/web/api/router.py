"""Router principal da API."""

from fastapi import APIRouter

from .monitoring import views as monitoring
from .webhooks import views as webhooks

router = APIRouter()
router.include_router(monitoring.router)
router.include_router(webhooks.router)

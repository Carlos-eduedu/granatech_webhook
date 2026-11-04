"""Health checks: processo vivo e banco acessível."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ....db.dependencies import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Health check do container; não toca no banco."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(
    db: Annotated[Session, Depends(get_db_session)],
) -> Any:
    """Verifica a conexão com o banco sem expor detalhes do erro."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("health check do banco falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"db": "erro"})
    return {"db": "ok"}

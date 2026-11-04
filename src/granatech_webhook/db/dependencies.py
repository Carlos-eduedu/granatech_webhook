"""Dependências de banco: uma sessão por requisição."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db_session(request: Request) -> Generator[Session]:
    """Entrega uma sessão da ``session_factory`` criada no lifespan."""
    factory = request.app.state.session_factory
    db: Session = factory()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

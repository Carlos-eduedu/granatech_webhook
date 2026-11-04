"""Fixtures compartilhadas: banco SQLite isolado e TestClient sem tocar no banco real."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Garante que, mesmo se o lifespan for executado, ele use um banco temporário.
# Isto roda antes dos imports da aplicação.
_DIR_SEGURANCA = tempfile.mkdtemp(prefix="granatech-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DIR_SEGURANCA}/seguranca.db"
os.environ["APP_ENV"] = "test"

from granatech_webhook.config import get_settings  # noqa: E402
from granatech_webhook.database import Base, get_db  # noqa: E402
from granatech_webhook.main import app  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# O logger do httpx (usado pelo TestClient) imprime a URL completa, inclusive
# ?token=. Em produção não há cliente HTTP de saída; silenciamos só nos testes.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Cada teste começa sem token/allowlist/proxy configurados."""
    for variavel in (
        "WEBHOOK_TOKEN",
        "WEBHOOK_TOKEN_HEADER",
        "ALLOWED_IPS",
        "TRUST_PROXY",
    ):
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_engine() -> Generator[Engine, None, None]:
    """Banco em memória compartilhado entre todas as conexões do teste."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=db_engine,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture
def make_client(
    session_factory: sessionmaker[Session],
) -> Generator[Callable[..., TestClient], None, None]:
    """Cria TestClients com o ``get_db`` apontando para o banco do teste."""

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    clientes: list[TestClient] = []

    def _criar(
        client_addr: tuple[str, int] | None = None,
    ) -> TestClient:
        kwargs: dict[str, Any] = {}
        if client_addr is not None:
            kwargs["client"] = client_addr
        cliente = TestClient(app, **kwargs)
        clientes.append(cliente)
        return cliente

    try:
        yield _criar
    finally:
        for cliente in clientes:
            cliente.close()
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    # Sem "with TestClient(app)": o lifespan não é executado nos testes,
    # por isso o banco real nunca é tocado.
    return make_client()


@pytest.fixture
def load_payload() -> Callable[[str], dict[str, Any]]:
    def _carregar(nome: str) -> dict[str, Any]:
        caminho = FIXTURES_DIR / nome
        return json.loads(caminho.read_text(encoding="utf-8"))

    return _carregar

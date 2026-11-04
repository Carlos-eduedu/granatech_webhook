"""Fixtures compartilhadas: banco isolado, settings e AsyncClient."""

import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Garante que, mesmo se o lifespan for executado, ele use um banco temporário.
# Isto roda antes dos imports da aplicação.
_DIR_SEGURANCA = tempfile.mkdtemp(prefix="granatech-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DIR_SEGURANCA}/seguranca.db"
os.environ["APP_ENV"] = "test"

from granatech_webhook import migrate  # noqa: E402
from granatech_webhook.db import models as _models  # noqa: E402,F401
from granatech_webhook.db.base import Base  # noqa: E402
from granatech_webhook.db.dependencies import get_db_session  # noqa: E402
from granatech_webhook.settings import (  # noqa: E402
    Settings,
    get_settings,
    normalizar_database_url,
)
from granatech_webhook.web.application import app  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# O logger do httpx (usado pelo AsyncClient) imprime a URL completa, inclusive
# ?token=. Em produção não há cliente HTTP de saída; silenciamos só nos testes.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
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
    yield


@pytest.fixture
def configurar_settings() -> Generator[Callable[..., Settings]]:
    """Troca o Settings via dependency_overrides (sem cache_clear)."""
    original = app.dependency_overrides.get(get_settings)

    def _configurar(**kwargs: Any) -> Settings:
        settings = Settings(
            database_url=os.environ.get("DATABASE_URL", "sqlite://"),
            app_env="test",
            webhook_token="",
            webhook_token_header="X-Webhook-Token",
            allowed_ips=[],
            trust_proxy=False,
            max_body_bytes=262144,
            log_level="INFO",
        ).model_copy(update=kwargs)
        app.dependency_overrides[get_settings] = lambda: settings
        return settings

    yield _configurar
    if original is None:
        app.dependency_overrides.pop(get_settings, None)
    else:
        app.dependency_overrides[get_settings] = original


def _aplicar_migracoes(url: str) -> None:
    config = migrate._config()
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def db_engine() -> Generator[Engine]:
    """Engine única da sessão; cada teste limpa as tabelas ao final.

    Com ``TEST_DATABASE_URL`` (PostgreSQL no CI), aplica as migrações uma vez.
    Sem ela, usa SQLite em memória e ``create_all`` para os testes locais.
    """
    url_teste = os.environ.get("TEST_DATABASE_URL")
    if url_teste:
        url = normalizar_database_url(url_teste)
        engine = create_engine(url, pool_pre_ping=True)
        if url.startswith("postgresql"):
            _aplicar_migracoes(url)
        else:
            Base.metadata.create_all(bind=engine)
        yield engine
        engine.dispose()
        return

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> Generator[sessionmaker[Session]]:
    """Sessões ligadas à engine do teste, com limpeza ao final.

    O service usa ``commit()`` internamente; por isso a limpeza é feita por
    ``DELETE`` ao final de cada teste, que isola SQLite e PostgreSQL igualmente.
    """
    fabrica = sessionmaker(
        bind=db_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield fabrica
    # Limpa na ordem inversa das dependências (histórico -> propostas etc.).
    with db_engine.begin() as conexao:
        for tabela in reversed(Base.metadata.sorted_tables):
            conexao.execute(tabela.delete())


@pytest.fixture
async def make_client(
    session_factory: sessionmaker[Session],
) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """Cria AsyncClients com o ``get_db_session`` apontando para o banco do teste."""

    def override_get_db_session() -> Generator[Session]:
        db = session_factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    clientes: list[httpx.AsyncClient] = []

    def _criar(
        client_addr: tuple[str, int] | None = None,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {}
        if client_addr is not None:
            kwargs["client"] = client_addr
        transport = httpx.ASGITransport(app=app, **kwargs)
        cliente = httpx.AsyncClient(transport=transport, base_url="http://test")
        clientes.append(cliente)
        return cliente

    try:
        yield _criar
    finally:
        for cliente in clientes:
            await cliente.aclose()
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
async def client(
    make_client: Callable[..., httpx.AsyncClient],
) -> httpx.AsyncClient:
    # Sem lifespan: o banco real nunca é tocado nos testes.
    return make_client()


@pytest.fixture
def load_payload() -> Callable[[str], dict[str, Any]]:
    def _carregar(nome: str) -> dict[str, Any]:
        caminho = FIXTURES_DIR / nome
        return json.loads(caminho.read_text(encoding="utf-8"))

    return _carregar

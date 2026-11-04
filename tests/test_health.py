"""Testes dos endpoints de health check."""

from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.db.dependencies import get_db_session
from granatech_webhook.web.application import app


@pytest.mark.anyio
async def test_health_nao_depende_do_banco(client: httpx.AsyncClient) -> None:
    def get_db_session_quebrado() -> Any:
        raise RuntimeError("não deveria ser chamado")

    app.dependency_overrides[get_db_session] = get_db_session_quebrado

    resposta = await client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_health_db_ok(client: httpx.AsyncClient) -> None:
    resposta = await client.get("/health/db")

    assert resposta.status_code == 200
    assert resposta.json() == {"db": "ok"}


@pytest.mark.anyio
async def test_health_db_erro_sem_detalhes(client: httpx.AsyncClient, tmp_path: Any) -> None:
    engine_quebrada = create_engine(f"sqlite:///{tmp_path}/diretorio/que/nao/existe/banco.db")
    fabrica = sessionmaker(bind=engine_quebrada)

    def get_db_session_quebrado() -> Any:
        db: Session = fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = get_db_session_quebrado

    resposta = await client.get("/health/db")

    assert resposta.status_code == 503
    assert resposta.json() == {"db": "erro"}


@pytest.mark.anyio
async def test_health_sem_autenticacao_com_token_configurado(
    client: httpx.AsyncClient, configurar_settings: Any
) -> None:
    configurar_settings(webhook_token="segredo")

    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/health/db")).status_code == 200

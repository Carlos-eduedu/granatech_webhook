"""Testes dos endpoints de health check."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook.config import get_settings
from granatech_webhook.database import get_db
from granatech_webhook.main import app


def test_health_nao_depende_do_banco(client: TestClient) -> None:
    def get_db_quebrado() -> Any:
        raise RuntimeError("não deveria ser chamado")

    app.dependency_overrides[get_db] = get_db_quebrado

    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_health_db_ok(client: TestClient) -> None:
    resposta = client.get("/health/db")

    assert resposta.status_code == 200
    assert resposta.json() == {"db": "ok"}


def test_health_db_erro_sem_detalhes(client: TestClient, tmp_path: Any) -> None:
    engine_quebrada = create_engine(
        f"sqlite:///{tmp_path}/diretorio/que/nao/existe/banco.db"
    )
    fabrica = sessionmaker(bind=engine_quebrada)

    def get_db_quebrado() -> Any:
        db: Session = fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_db_quebrado

    resposta = client.get("/health/db")

    assert resposta.status_code == 503
    assert resposta.json() == {"db": "erro"}


def test_health_sem_autenticacao_com_token_configurado(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("WEBHOOK_TOKEN", "segredo")
    get_settings.cache_clear()

    assert client.get("/health").status_code == 200
    assert client.get("/health/db").status_code == 200

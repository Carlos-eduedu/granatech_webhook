"""Prova que uma rota síncrona presa no banco não bloqueia o event loop."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from granatech_webhook import services
from granatech_webhook.main import app


@pytest.mark.anyio
async def test_health_responde_enquanto_webhook_esta_preso_no_banco(
    make_client: Callable[..., TestClient],
    load_payload: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # make_client instala o override de get_db para o banco do teste.
    make_client()
    original = services._processar_consulta_uma_vez

    def processamento_lento(
        db: Session, evento: Any, payload: Any
    ) -> bool:
        time.sleep(1.0)
        return original(db, evento, payload)

    monkeypatch.setattr(
        services, "_processar_consulta_uma_vez", processamento_lento
    )

    payload = load_payload("consulta_SUCCESS.json")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        webhook = asyncio.create_task(
            client.post("/webhooks/granatech", json=payload)
        )
        await asyncio.sleep(0.15)

        inicio = time.perf_counter()
        health = await client.get("/health")
        duracao = time.perf_counter() - inicio

        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert duracao < 0.5, f"/health demorou {duracao:.2f}s"

        resposta = await webhook
        assert resposta.status_code == 200, resposta.text

"""Testes unitários de infraestrutura e casos de borda (cobertura)."""

from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from granatech_webhook import migrate
from granatech_webhook.db.base import criar_engine
from granatech_webhook.db.dependencies import get_db_session
from granatech_webhook.settings import (
    DATABASE_URL_PADRAO,
    Settings,
    get_settings,
)
from granatech_webhook.web import lifespan as lifespan_module
from granatech_webhook.web.api.webhooks import dependencies, service
from granatech_webhook.web.api.webhooks.schemas import (
    ConsultaPayload,
    PropostaPayload,
)
from granatech_webhook.web.api.webhooks.utils import (
    hash_payload,
    mascarar_cpf,
    normalizar_cpf,
    normalizar_uuid_tolerante,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_tolera_valores_invalidos() -> None:
    settings = Settings.from_env(
        {
            "DATABASE_URL": "",
            "PORT": "abc",
            "MAX_BODY_BYTES": "x",
            "TRUST_PROXY": "sim",
            "ALLOWED_IPS": " 10.0.0.1, , 10.0.0.2 ",
        }
    )

    assert settings.database_url == DATABASE_URL_PADRAO
    assert settings.port == 8000
    assert settings.max_body_bytes == 262144
    assert settings.trust_proxy is True
    assert settings.allowed_ips == ["10.0.0.1", "10.0.0.2"]


def test_settings_from_env_le_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    get_settings.cache_clear()
    try:
        assert Settings.from_env().app_env == "staging"
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cpf", "esperado"),
    [
        (None, "***"),
        ("1234", "***"),
        ("33179781041", "331.***.***-41"),
        ("331.797.810-41", "331.***.***-41"),
    ],
)
def test_mascarar_cpf(cpf: str | None, esperado: str) -> None:
    assert mascarar_cpf(cpf) == esperado


def test_normalizar_cpf_vazio() -> None:
    with pytest.raises(ValueError, match="vazio"):
        normalizar_cpf("...")


def test_normalizar_uuid_invalido_nao_quebra() -> None:
    assert normalizar_uuid_tolerante("nao-e-uuid", "id_proposta") == "nao-e-uuid"


# ---------------------------------------------------------------------------
# DB base/dependencies
# ---------------------------------------------------------------------------


def test_criar_engine_sqlite_e_postgres() -> None:
    sqlite = criar_engine("sqlite://")
    assert sqlite.dialect.name == "sqlite"
    sqlite.dispose()

    postgres = criar_engine("postgresql+psycopg://u:p@localhost/db")
    assert postgres.dialect.name == "postgresql"
    postgres.dispose()


def test_get_db_session_entrega_e_rollback(
    session_factory: sessionmaker[Session],
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=session_factory))
    )
    gerador = get_db_session(request)  # type: ignore[arg-type]
    db = next(gerador)
    assert db.execute(text("SELECT 1")).scalar() == 1

    with pytest.raises(RuntimeError):
        gerador.throw(RuntimeError("falha simulada"))


def test_ip_cliente_sem_client() -> None:
    request = SimpleNamespace(headers={}, client=None)
    settings = Settings(trust_proxy=False)
    assert dependencies.ip_cliente(request, settings) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_consulta_id_proposta_vazio_ou_nulo(load_payload: Any) -> None:
    base = load_payload("consulta_PENDING.json")
    for valor in ("", None):
        dados = {**base, "id_proposta": valor}
        payload = ConsultaPayload.model_validate(dados)
        assert payload.id_proposta is None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifespan_cria_e_descarta_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/lifespan.db",
        app_env="test",
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    app = FastAPI()

    async with lifespan_module.lifespan(app):
        with app.state.session_factory() as db:
            assert db.execute(text("SELECT 1")).scalar() == 1

    app.state.engine.dispose()


@pytest.mark.anyio
async def test_lifespan_avisa_producao_sem_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/lifespan-prod.db",
        app_env="production",
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    app = FastAPI()

    async with lifespan_module.lifespan(app):
        pass
    app.state.engine.dispose()


# ---------------------------------------------------------------------------
# Migrações
# ---------------------------------------------------------------------------


def _config_migracao(banco: Any) -> Any:
    config = migrate._config()
    url = f"sqlite:///{banco}"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _versao(banco: Any) -> str:
    import sqlite3

    with sqlite3.connect(banco) as conexao:
        linha = conexao.execute("SELECT version_num FROM alembic_version").fetchone()
    assert linha is not None
    return str(linha[0])


def test_migrate_main_banco_novo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    banco = tmp_path / "novo.db"
    settings = Settings(database_url=f"sqlite:///{banco}")
    monkeypatch.setattr(migrate, "get_settings", lambda: settings)

    migrate.main()

    assert _versao(banco) == "0003_campos_opcionais_consulta"
    engine = create_engine(f"sqlite:///{banco}")
    assert migrate.precisa_de_stamp(engine) is False
    engine.dispose()


def test_migrate_main_banco_criado_pelo_create_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    banco = tmp_path / "antigo.db"
    config = _config_migracao(banco)
    command.upgrade(config, "0001_baseline")

    engine = create_engine(f"sqlite:///{banco}")
    with engine.begin() as conexao:
        conexao.execute(text("DROP TABLE alembic_version"))
    assert migrate.precisa_de_stamp(engine) is True
    engine.dispose()

    settings = Settings(database_url=f"sqlite:///{banco}")
    monkeypatch.setattr(migrate, "get_settings", lambda: settings)

    migrate.main()

    assert _versao(banco) == "0003_campos_opcionais_consulta"


# ---------------------------------------------------------------------------
# Service: casos de borda
# ---------------------------------------------------------------------------


def test_bloquear_entidade_ignora_chave_vazia_e_chama_daos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        service.consulta_dao,
        "bloquear",
        lambda _db, ident: chamadas.append(("consulta", ident)),
    )
    monkeypatch.setattr(
        service.proposta_dao,
        "bloquear",
        lambda _db, ident: chamadas.append(("proposta", ident)),
    )

    service._bloquear_entidade(SimpleNamespace(), None)
    service._bloquear_entidade(SimpleNamespace(), "proposta:")
    service._bloquear_entidade(SimpleNamespace(), "consulta:abc")
    service._bloquear_entidade(SimpleNamespace(), "proposta:def")

    assert chamadas == [("consulta", "abc"), ("proposta", "def")]


def test_registrar_bruto_converte_falha(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> None:
    def explodir(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("falha de banco")

    monkeypatch.setattr(service, "registrar_evento", explodir)
    with session_factory() as db, pytest.raises(service.FalhaRegistro):
        service._registrar_bruto(
            db,
            tipo=None,
            rota="/webhooks/granatech",
            ip_origem=None,
            headers={},
            payload={},
            payload_hash="x",
        )


def test_marcar_evento_falha_inexistente(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        service.marcar_evento_falha(db, 999999, "erro")


def test_marcar_evento_falha_nao_derruba(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DbQuebrado:
        def rollback(self) -> None:
            pass

        def get(self, *_args: Any) -> Any:
            return SimpleNamespace(processado=True, erro=None)

        def commit(self) -> None:
            raise RuntimeError("commit quebrado")

    service.marcar_evento_falha(DbQuebrado(), 1, "erro")  # type: ignore[arg-type]


def test_registrar_evento_trata_corrida_de_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existente = SimpleNamespace(processado=True)
    chamadas = {"n": 0}

    def buscar(*_args: Any, **_kwargs: Any) -> Any:
        chamadas["n"] += 1
        return None if chamadas["n"] == 1 else existente

    class DbCorrida:
        def add(self, *_args: Any) -> None:
            pass

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            raise IntegrityError("stmt", {}, Exception())

        def rollback(self) -> None:
            pass

    monkeypatch.setattr(service, "_buscar_existente", buscar)
    monkeypatch.setattr(service.evento_dao, "criar", lambda *_args, **_kwargs: SimpleNamespace())

    resultado = service.registrar_evento(
        DbCorrida(),  # type: ignore[arg-type]
        tipo=None,
        rota="/",
        ip_origem=None,
        headers={},
        payload={},
        payload_hash="x",
    )

    assert resultado.duplicado is True
    assert chamadas["n"] == 2


@pytest.mark.anyio
async def test_evento_nao_processado_sem_erro_e_duplicado(
    client: Any,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_PENDING.json")
    with session_factory() as db:
        resultado = service.registrar_evento(
            db,
            tipo="consulta",
            rota="/webhooks/granatech",
            ip_origem=None,
            headers={},
            payload=payload,
            payload_hash=hash_payload(payload),
            chave_entidade=f"consulta:{payload['id_solicitacao']}",
        )
        assert resultado.duplicado is False

    resposta = await client.post("/webhooks/granatech", json=payload)

    assert resposta.status_code == 200
    assert resposta.json()["duplicado"] is True


@pytest.mark.anyio
async def test_consulta_atualiza_registro_existente(
    client: Any,
    load_payload: Any,
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload("consulta_PENDING.json")
    assert (await client.post("/webhooks/granatech", json=payload)).status_code == 200

    atualizado = {
        **payload,
        "status": "SUCCESS",
        "cpf": "11144477735",
        "id_proposta": None,
    }
    resposta = await client.post("/webhooks/granatech", json=atualizado)

    assert resposta.status_code == 200
    with session_factory() as db:
        from granatech_webhook.db.models import Consulta

        consulta = db.get(Consulta, payload["id_solicitacao"])
        assert consulta is not None
        assert consulta.status == "SUCCESS"
        assert consulta.cpf == "11144477735"
        assert consulta.id_proposta == payload["id_proposta"]


def test_processar_consulta_retry_em_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    load_payload: Any,
) -> None:
    payload = load_payload("consulta_PENDING.json")
    with session_factory() as db:
        evento = service.registrar_evento(
            db,
            tipo="consulta",
            rota="/",
            ip_origem=None,
            headers={},
            payload=payload,
            payload_hash=hash_payload(payload),
            chave_entidade=f"consulta:{payload['id_solicitacao']}",
        ).evento
        original = service._processar_consulta_uma_vez
        chamadas = {"n": 0}

        def instavel(*args: Any) -> Any:
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise IntegrityError("stmt", {}, Exception())
            return original(*args)

        monkeypatch.setattr(service, "_processar_consulta_uma_vez", instavel)

        assert service.processar_consulta(db, evento, ConsultaPayload.model_validate(payload))
        assert chamadas["n"] == 2


def test_processar_proposta_retry_em_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    load_payload: Any,
) -> None:
    payload = load_payload("proposta_PENDING_CONFIRMATION__AGUARDANDO_CONFIRMACAO.json")
    with session_factory() as db:
        evento = service.registrar_evento(
            db,
            tipo="proposta",
            rota="/",
            ip_origem=None,
            headers={},
            payload=payload,
            payload_hash=hash_payload(payload),
            chave_entidade=f"proposta:{payload['id_proposta']}",
        ).evento
        original = service._processar_proposta_uma_vez
        chamadas = {"n": 0}

        def instavel(*args: Any) -> Any:
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise IntegrityError("stmt", {}, Exception())
            return original(*args)

        monkeypatch.setattr(service, "_processar_proposta_uma_vez", instavel)

        assert service.processar_proposta(db, evento, PropostaPayload.model_validate(payload))
        assert chamadas["n"] == 2

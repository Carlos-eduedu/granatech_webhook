# Granatech Webhook — MEX Promotora

Receptor dos webhooks da **Granatech** para consignado CLT/FGTS. Recebe, valida,
registra e persiste notificações de **consultas** (saldo/margem) e **propostas**
(ciclo de vida completo). Não faz chamadas de saída para a API Granatech, não
envia WhatsApp e não possui front-end.

## Stack

- Python 3.15
- FastAPI + Pydantic v2
- SQLAlchemy 2.x (`Mapped`/`mapped_column`, sessão síncrona)
- Alembic para migrações
- SQLite local/testes e PostgreSQL em produção (`psycopg` 3)
- `uv` para dependências, execução e lock (`uv.lock` versionado)
- Ruff, mypy estrito e pytest com cobertura mínima de 90%

As rotas são síncronas de propósito: o acesso ao SQLAlchemy síncrono roda no
threadpool do FastAPI e não bloqueia o event loop. A única parte assíncrona do
fluxo é a leitura do corpo da requisição.

## Estrutura

```
src/granatech_webhook/
├── __init__.py            # comando `granatech-webhook`
├── __main__.py            # `uv run -m granatech_webhook`
├── main.py                # ASGI de compatibilidade (`granatech_webhook.main:app`)
├── migrate.py             # stamp automático + `alembic upgrade head`
├── settings.py            # pydantic-settings, sem env_prefix
├── log.py                 # logging em stdout + filtro de CPF
├── db/
│   ├── base.py            # DeclarativeBase, naming convention e engine
│   ├── dependencies.py    # get_db_session (app.state.session_factory)
│   ├── models/            # evento, consulta, proposta e histórico
│   └── dao/               # queries sem regra de negócio
└── web/
    ├── application.py     # create_app, docs condicionais e exception handlers
    ├── lifespan.py        # engine + session factory + logging
    └── api/
        ├── router.py
        ├── monitoring/    # /health e /health/db
        └── webhooks/      # views, dependencies, schemas, service, etc.
migrations/                # Alembic (0001_baseline e 0002_idempotencia...)
scripts/entrypoint.sh      # migra e sobe o uvicorn (usado no Docker)
tests/
├── fixtures/              # payloads de exemplo
├── conftest.py            # SQLite por padrão; PostgreSQL com TEST_DATABASE_URL
└── test_*.py
```

## Instalação

Pré-requisito: [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

## Como rodar

```bash
# aplica as migrações no banco configurado em DATABASE_URL
uv run alembic upgrade head

# comando instalado pelo projeto
uv run granatech-webhook

# equivalente, sem depender do script instalado
uv run -m granatech_webhook
```

Ou diretamente com uvicorn:

```bash
uv run uvicorn granatech_webhook.web.application:app \
  --host 0.0.0.0 --port 8000 --no-access-log
```

`--no-access-log` evita que um eventual `?token=` apareça no log de acesso. No
lugar dele, a aplicação loga uma linha no início e outra no fim de cada
requisição, sem a query string (veja [LGPD e logs](#lgpd-e-logs)).

Sem `DATABASE_URL`, o padrão é `sqlite:///./granatech_webhook.db` (arquivo no
diretório corrente). Em produção use sempre PostgreSQL.

## Variáveis de ambiente

Os nomes são exatamente os já configurados no Dokploy. **Não há prefixo novo.**

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./granatech_webhook.db` | SQLite local ou PostgreSQL. `postgres://` e `postgresql://` são normalizados para `postgresql+psycopg://`. |
| `WEBHOOK_TOKEN` | vazio | Token compartilhado. Vazio = endpoint sem autenticação. |
| `WEBHOOK_TOKEN_HEADER` | `X-Webhook-Token` | Header do token. `?token=...` também é aceito por compatibilidade. |
| `ALLOWED_IPS` | vazio | IPs permitidos separados por vírgula. Vazio = libera todos. `*` também libera. |
| `TRUST_PROXY` | `false` | `true` atrás do Traefik: usa o **primeiro** IP de `X-Forwarded-For`. |
| `APP_ENV` | `development` | Em `production`, esconde `/docs`, `/redoc` e `/openapi.json` e loga WARNING se não houver token. |
| `LOG_LEVEL` | `INFO` | Nível de log (stdout), aplicado também aos loggers do uvicorn após o startup. |
| `MAX_BODY_BYTES` | `262144` | Limite do corpo em bytes (256 KB). Acima disso: `413` e o evento **não** é gravado. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Usados por `uv run granatech-webhook`. |

O IP gravado em `ip_origem` e o usado em `ALLOWED_IPS` vêm da mesma função:
com `TRUST_PROXY=true` é o primeiro IP de `X-Forwarded-For`; sem proxy é
`request.client.host`.

> **Autenticação:** a documentação da Granatech não especifica assinatura/token.
> Implementamos token por header (configurável) e mantivemos `?token=` como
> compatibilidade. **Recomendação:** use sempre o header, porque a URL com
> `?token=` pode aparecer em logs do Traefik/Dokploy.

## Endpoints

| Método | Rota | Autenticação | Banco |
|---|---|---|---|
| GET | `/health` | não | não toca |
| GET | `/health/db` | não | `SELECT 1`; 200 `{"db":"ok"}` ou 503 `{"db":"erro"}` |
| POST | `/webhooks/granatech` | conforme config | endpoint único, tipo pelo campo `tipo` |
| POST | `/webhooks/granatech/consultas` | conforme config | alias que força `consulta` |
| POST | `/webhooks/granatech/propostas` | conforme config | alias que força `proposta` |

O campo `tipo` é comparado sem diferenciar maiúsculas/minúsculas (`CONSULTA`,
`consulta`, `Proposta` etc.).

### Respostas

- Sucesso: `200 {"recebido": true, "evento_id": 123, "duplicado": false}`
- Duplicado (mesmo payload do último evento da entidade): `200` com
  `"duplicado": true`, sem reprocessar
- Token ausente/errado: `401`
- IP fora de `ALLOWED_IPS`: `403`
- JSON malformado: `400` (o corpo cru é registrado)
- JSON válido mas campos obrigatórios faltando ou `tipo` desconhecido: `422`.
  O evento bruto é gravado com `processado=false` e `erro` preenchido.
- Corpo acima de `MAX_BODY_BYTES`: `413` sem gravar evento
- Falha ao registrar/processar: `500` para a Granatech reenviar
- Status desconhecido: `200`, gravado normalmente, com
  `status_conhecido=false` e WARNING no log. Status novos não quebram o webhook.

### Idempotência

O `payload_hash` é o SHA-256 do JSON canonizado (`sort_keys=True`). Ele **não**
é único globalmente. A deduplicação é feita por entidade
(`consulta:<id_solicitacao>` ou `proposta:<id_proposta>`), na coluna
`chave_entidade` de `granatech_webhook_eventos`.

- O mesmo payload enviado duas vezes seguidas é retentativa: responde `200` com
  `duplicado=true` e não cria histórico novo.
- Se o payload for diferente do **último** evento da entidade, é um evento novo,
  mesmo que já tenha existido um payload igual no passado. Isso preserva as
  "idas e voltas" de status documentadas pela Granatech.
- Se o último evento da entidade falhou no **processamento** (`500`), o reenvio
  idêntico reprocessa o mesmo evento e responde `duplicado=false`.
- Eventos sem entidade (JSON malformado, `tipo` desconhecido, falha de
  validação) continuam deduplicados pelo hash.

No PostgreSQL a linha da consulta/proposta é bloqueada com `SELECT ... FOR
UPDATE` durante a checagem de concorrência. No SQLite isso não é necessário.

## Payloads

### Consulta

```json
{
  "id_solicitacao": "a7e3587e-cd73-4998-bae3-ec000ab6bb6b",
  "id_proposta": "6fdf2acb-cd75-416f-8754-3744e786a6a6",
  "cpf": "33179781041",
  "status": "AWAITING_CLIENT_AUTHORIZATION",
  "user_id": "12500542068.38",
  "corban_id": 38,
  "tipo": "CONSULTA"
}
```

Status conhecidos: `AWAITING_CLIENT_AUTHORIZATION`, `PROCESSING`, `SUCCESS`,
`PENDING`, `NO_MARGIN`, `USED`, `UNEXPECTED_ERROR`.
Finais: `SUCCESS`, `NO_MARGIN`, `USED`, `UNEXPECTED_ERROR`.

O CPF é normalizado para apenas dígitos com `zfill(11)` (zeros à esquerda são
preservados). `user_id` permanece **string**, exatamente como recebido.

### Proposta

```json
{
  "tipo": "proposta",
  "status_da_proposta": "PENDING_CONFIRMATION",
  "tipo_notificacao": "AGUARDANDO_CONFIRMACAO",
  "id_proposta": "6fdf2acb-cd75-416f-8754-3744e786a6a6",
  "informacoes": "Proposta criada com sucesso na plataforma"
}
```

A combinação `status_da_proposta` + `tipo_notificacao` define o evento. O status
atual é sempre o do último evento recebido; o histórico completo fica em
`granatech_propostas_historico`. **Não há máquina de estados que rejeite
transições** — a documentação da Granatech mostra idas e voltas. Eventos depois
de um status final são aceitos e geram WARNING.

`informacoes` pode ser `null` ou ausente; nesses casos é gravado `""`.

Status finais: `PAYED`, `CANCELED`, `REPROVED`.
A Granatech usa a grafia `PAYED`; o valor é preservado exatamente assim. Tanto
`PAGO` quanto `PROPOSTA_PAGA` significam proposta paga.

Todas as combinações documentadas estão em
`src/granatech_webhook/web/api/webhooks/constants.py` e nos fixtures de
`tests/fixtures/`.

## Exemplos com curl

Consulta:

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  --data @tests/fixtures/consulta_AWAITING_CLIENT_AUTHORIZATION.json
```

Proposta:

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  --data @tests/fixtures/proposta_PENDING_CONFIRMATION__AGUARDANDO_CONFIRMACAO.json
```

Aliases (o tipo é forçado pela rota):

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech/consultas \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/consulta_SUCCESS.json
```

Health checks:

```bash
curl https://SEU-DOMINIO/health
curl https://SEU-DOMINIO/health/db
```

## Banco de dados

- `granatech_webhook_eventos` — log bruto de tudo (payload, headers mascarados,
  IP, rota, `payload_hash`, `chave_entidade`, processado/erro/status_conhecido)
- `granatech_consultas` — estado atual por `id_solicitacao`
- `granatech_propostas` — estado atual por `id_proposta`
- `granatech_propostas_historico` — uma linha por notificação de proposta
- `alembic_version` — controle de migrações

O evento bruto é sempre gravado primeiro, em transação própria. Depois o
upsert + histórico acontece em outra transação. Se o processamento falhar, o
evento é marcado com erro e a resposta é `500`.

Quando uma consulta traz `id_proposta`, o CPF é copiado para a proposta se ela
existir e ainda não tiver CPF. Ao criar a proposta, o CPF é buscado na consulta
associada.

## Testes e qualidade

```bash
# SQLite em memória (padrão), com cobertura mínima de 90%
uv run pytest

# PostgreSQL local (sobe só o banco do compose)
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/granatech \
  uv run pytest

# lint, formatação e tipos
uv run ruff check .
uv run ruff format --check .
uv run mypy src

# hooks de pre-commit (ruff, ruff-format e mypy)
uv run pre-commit install
uv run pre-commit run --all-files
```

Os testes HTTP usam `httpx.AsyncClient` + `ASGITransport` com
`@pytest.mark.anyio` (sem `TestClient`). Com `TEST_DATABASE_URL` definida, a
fixture de sessão roda `alembic upgrade head` no PostgreSQL e cada teste é
isolado com limpeza das tabelas. Sem a variável, os testes usam SQLite em
memória e `create_all` apenas no ambiente de teste.

Os testes cobrem todos os fixtures de consulta e proposta, idempotência,
retentativa após `500`, idas e voltas de status, status desconhecido, 413,
422/400, token, allowlist, IP via proxy, normalização de URL PostgreSQL, LGPD
nos logs e migrações.

## Docker local

```bash
docker compose up --build
curl http://127.0.0.1:8000/health
```

Ou somente a imagem:

```bash
docker build -t granatech-webhook .
docker run --rm -p 8000:8000 --env-file .env granatech-webhook
```

O Dockerfile é multi-stage, usa `uv` com `uv.lock`, roda como usuário não-root,
expõe a porta 8000 e tem `HEALTHCHECK` sem depender de `curl`. O entrypoint
(`scripts/entrypoint.sh`) aplica as migrações antes de subir o uvicorn. O access
log do uvicorn fica desligado para não registrar `?token=`; a aplicação loga
cada requisição em stdout (início, etapas, status e duração).

## CI

O workflow `.github/workflows/ci.yml` roda, a cada push/PR:

1. `uv sync --locked`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run mypy src`
5. `uv run pytest` com um service `postgres:17` e `TEST_DATABASE_URL`

## Deploy no Dokploy

O Dokploy usa Application com **Build Type: Dockerfile**, Traefik na frente
(domínio/HTTPS) e um PostgreSQL criado no próprio Dokploy.

### 1. Criar o PostgreSQL

1. No Dokploy, crie um recurso **Database → PostgreSQL**.
2. Copie a **Internal Connection URL** (algo como
   `postgresql://usuario:senha@postgres:5432/banco`).
3. Essa URL será o `DATABASE_URL` da aplicação. `postgres://` e
   `postgresql://` são aceitos e normalizados para o driver `psycopg` 3.
4. Se a senha tiver caracteres especiais, use a URL já codificada pelo Dokploy.

### 2. Criar a Application

1. Crie uma **Application** apontando para o repositório do GitHub.
2. Em **Build Type**, escolha **Dockerfile**.
3. Dockerfile Path: `Dockerfile`; Docker Context Path: `.`.
4. Exponha a porta **8000** do container no roteamento/domínio.
5. O entrypoint aplica as migrações antes de subir o uvicorn.

### 3. Variáveis de ambiente da Application

```
APP_ENV=production
TRUST_PROXY=true
WEBHOOK_TOKEN=<token-forte-gerado-por-voce>
WEBHOOK_TOKEN_HEADER=X-Webhook-Token
# opcional, depois de confirmar os IPs com a Granatech:
# ALLOWED_IPS=203.0.113.10,203.0.113.11
DATABASE_URL=<Internal Connection URL do PostgreSQL do Dokploy>
LOG_LEVEL=INFO
# opcional: limite do corpo em bytes (padrão 262144 = 256 KB)
# MAX_BODY_BYTES=262144
```

Sem `WEBHOOK_TOKEN` em produção, o startup loga um WARNING bem visível porque o
endpoint fica público na internet. Com `APP_ENV=production`, `/docs`, `/redoc` e
`/openapi.json` ficam desabilitados (404).

### 4. Domínio e HTTPS

1. Em **Domains**, adicione o domínio do webhook.
2. Aponte para a porta **8000** do container.
3. Ative HTTPS (Let's Encrypt gerenciado pelo Traefik).
4. Valide: `https://SEU-DOMINIO/health` deve retornar `{"status":"ok"}`.
5. Confirme que `TRUST_PROXY=true` para que `ip_origem` venha do
   `X-Forwarded-For` (primeiro IP) e a allowlist funcione atrás do Traefik.

### 5. Health check

Em **Advanced → Cluster Settings → Swarm Settings → Health Check**, cole:

```json
{
  "Test": ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"],
  "Interval": 30000000000,
  "Timeout": 10000000000,
  "StartPeriod": 30000000000,
  "Retries": 3
}
```

O endpoint `/health` não toca no banco de propósito; `/health/db` verifica o
PostgreSQL, mas não deve ser usado como health check do container.

### 6. Auto Deploy

Ative **Auto Deploy** para que cada push no GitHub faça o redeploy automático.
Após o deploy, acompanhe os logs do container no Dokploy (tudo vai para stdout).

## Atualizando um banco que já está em produção

O entrypoint executa `python -m granatech_webhook.migrate` antes do uvicorn. Ele
detecta automaticamente o estado do banco:

- **Banco vazio:** `alembic upgrade head` cria tudo (`0001_baseline` e
  `0002_idempotencia_por_entidade`).
- **Banco criado pela versão antiga** (tabelas existem, mas não existe
  `alembic_version`): faz `stamp 0001_baseline` e depois `upgrade head`. A
  migração `0002` adiciona `chave_entidade` e troca o índice UNIQUE de
  `payload_hash` por um índice comum, **preservando os dados existentes**.
- **Banco já migrado:** `upgrade head` é no-op.

Recomendações para o primeiro deploy:

1. Faça backup do PostgreSQL antes do deploy.
2. Suba com **1 réplica** durante a migração. O Alembic não é seguro para várias
   instâncias migrando ao mesmo tempo; depois que a versão estiver em `head`,
   você pode escalar.
3. Se a migração falhar, o container não sobe o uvicorn (fail-fast). Verifique
   os logs no Dokploy antes de liberar tráfego.

## LGPD e logs

- CPF completo **nunca** é logado. O filtro de logging mascara padrões de CPF em
  mensagens, argumentos e no texto final (inclusive stack traces); o formato
  `331.***.***-41` está disponível para logs manuais.
- O valor do token nunca é gravado nos headers do evento (fica `"***"`).
- A query string não é gravada em `rota` e o access log do uvicorn é desligado.
- Logs em stdout, uma linha por evento, com timestamp, nível e `request_id`:

```text
2026-11-04 12:00:00,000 INFO request_id=ef6318c17a5f439a logger=granatech_webhook.web.application requisição recebida metodo=POST rota=/webhooks/granatech ip=203.0.113.10 content_length=231
2026-11-04 12:00:00,015 INFO request_id=ef6318c17a5f439a logger=granatech_webhook.web.api.webhooks.service payload validado tipo=consulta id=... status=SUCCESS
2026-11-04 12:00:00,031 INFO request_id=ef6318c17a5f439a logger=granatech_webhook.web.api.webhooks.service evento bruto gravado evento_id=42 rota=/webhooks/granatech duplicado=não
2026-11-04 12:00:00,032 INFO request_id=ef6318c17a5f439a logger=granatech_webhook.web.api.webhooks.service evento tipo=consulta id=... status=SUCCESS tipo_notificacao=- evento_id=42 duplicado=não
2026-11-04 12:00:00,033 INFO request_id=ef6318c17a5f439a logger=granatech_webhook.web.application resposta status=200 duracao_ms=33.1 metodo=POST rota=/webhooks/granatech
```

- `request_id` correlaciona todas as linhas da mesma requisição (também em
  401/403/413 e resultados duplicados). `/health` e `/health/db` ficam fora do
  log para não poluir o painel.
- Erros trazem stack trace (`logger.exception`); um CPF presente na mensagem do
  driver é mascarado antes de chegar ao stdout.

## Decisões tomadas por falta de informação

- A Granatech não documenta autenticação/assinatura. Implementamos token por
  header configurável e mantivemos `?token=` como compatibilidade.
- Não há documentação sobre o payload exato de "consulta-saldo pronta" e
  "proposta finalizada nos terceiros"; o schema aceita campos extras
  (`extra="allow"`) e preserva o payload bruto para não perder informação.
- A política de retentativa da Granatech não é conhecida; o webhook responde
  `500` em falha de processamento e `200` em duplicidade/retentativa bem-sucedida
  para não gerar reenvios infinitos.
- Status desconhecidos são aceitos de propósito (sem máquina de estados), porque
  a Granatech pode adicionar novos status. A grafia `PAYED` é preservada.

## Pendências a confirmar com a Granatech

- Mecanismo de autenticação/assinatura do webhook (token? HMAC? qual header?).
- Se usam uma URL única ou URLs separadas para consulta e proposta.
- Política de retentativa: quantas vezes, intervalo e quais códigos HTTP
  disparam reenvio.
- Payload exato das notificações "consulta-saldo pronta" e "proposta finalizada
  nos terceiros".
- IPs de origem para a allowlist (`ALLOWED_IPS`), considerando o proxy.

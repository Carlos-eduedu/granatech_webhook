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

As tabelas são criadas/atualizadas por migrações do Alembic. O entrypoint do
container roda `alembic upgrade head` antes do uvicorn (com `stamp` automático
em bancos criados pela versão antiga, que usava `create_all()`).

## Estrutura

```
src/granatech_webhook/
├── __init__.py        # comando `granatech-webhook` (uvicorn)
├── main.py            # FastAPI, lifespan, /health e /health/db
├── config.py          # Settings lendo os.environ
├── database.py        # engine, SessionLocal, Base e get_db
├── models.py          # tabelas SQLAlchemy
├── schemas.py         # payloads Pydantic tolerantes
├── enums.py           # status conhecidos, descrições e finais
├── security.py        # token, IP real/allowlist e headers mascarados
├── services.py        # evento bruto, upserts, histórico e idempotência
└── routers/webhooks.py
tests/
├── fixtures/          # payloads de exemplo de todas as combinações
├── conftest.py
├── test_consultas.py
├── test_propostas.py
├── test_seguranca.py
├── test_config.py
└── test_health.py
```

## Instalação

Pré-requisito: [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Crie o arquivo de ambiente local:

```bash
cp .env.example .env
```

## Como rodar

```bash
# lê HOST/PORT do ambiente (padrão 0.0.0.0:8000)
uv run granatech-webhook
```

Ou diretamente com uvicorn:

```bash
uv run uvicorn granatech_webhook.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

`--no-access-log` evita que um eventual `?token=` apareça no log de acesso.

Para carregar o `.env` no shell local:

```bash
set -a; source .env; set +a
uv run granatech-webhook
```

Sem `DATABASE_URL`, o padrão é `sqlite:///./granatech_webhook.db` (arquivo no
diretório corrente). Em produção use sempre PostgreSQL.

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./granatech_webhook.db` | SQLite local ou PostgreSQL. `postgres://` e `postgresql://` são normalizados para `postgresql+psycopg://`. |
| `WEBHOOK_TOKEN` | vazio | Token compartilhado. Vazio = endpoint sem autenticação. |
| `WEBHOOK_TOKEN_HEADER` | `X-Webhook-Token` | Header do token. `?token=...` também é aceito. |
| `ALLOWED_IPS` | vazio | IPs permitidos separados por vírgula. Vazio = libera todos. `*` também libera. |
| `TRUST_PROXY` | `false` | `true` atrás do Traefik: usa o **primeiro** IP de `X-Forwarded-For`. |
| `APP_ENV` | `development` | Em `production` sem token, loga um WARNING no startup. |
| `LOG_LEVEL` | `INFO` | Nível de log (stdout). |
| `MAX_BODY_BYTES` | `262144` | Limite do corpo em bytes. Acima disso: `413` e o evento **não** é gravado. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Usados por `uv run granatech-webhook`. |

O IP gravado em `ip_origem` e o usado em `ALLOWED_IPS` vêm da mesma função:
com `TRUST_PROXY=true` é o primeiro IP de `X-Forwarded-For`; sem proxy é
`request.client.host`.

> **TODO:** confirmar com a Granatech se eles enviam assinatura/token e em qual
> header. A documentação deles não especifica autenticação. Implementamos token
> por header (configurável) e, como alternativa, `?token=` na URL.

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
- Duplicado (mesmo payload): `200` com `"duplicado": true`, sem reprocessar
- Token ausente/errado: `401`
- IP fora de `ALLOWED_IPS`: `403`
- JSON malformado: `400` (o corpo cru é registrado)
- JSON válido mas campos obrigatórios faltando ou `tipo` desconhecido: `422`.
  O evento bruto é gravado com `processado=false` e `erro` preenchido.
- Falha ao processar/persistir: `500` para a Granatech reenviar
- Status desconhecido: `200`, gravado normalmente, com
  `status_conhecido=false` e WARNING no log. Status novos não quebram o webhook.

### Idempotência

O `payload_hash` é o SHA-256 do JSON canonizado (`sort_keys=True`). Ele **não**
é mais único globalmente: a deduplicação é feita por entidade
(`consulta:<id_solicitacao>` ou `proposta:<id_proposta>`).

- O mesmo payload enviado duas vezes seguidas é retentativa: responde `200` com
  `duplicado=true` e não cria histórico novo.
- Se o payload for diferente do **último** evento da entidade, é um evento novo,
  mesmo que já tenha existido um payload igual no passado. Isso preserva as
  "idas e voltas" de status documentadas pela Granatech.
- Se o último evento da entidade falhou no **processamento** (`500`), o reenvio
  idêntico reprocessa o mesmo evento e responde `duplicado=false`.
- Eventos sem entidade (JSON malformado, `tipo` desconhecido, falha de
  validação) continuam deduplicados pelo hash.

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

Status finais: `PAYED`, `CANCELED`, `REPROVED`.
A Granatech usa a grafia `PAYED`; o valor é preservado exatamente assim. Tanto
`PAGO` quanto `PROPOSTA_PAGA` significam proposta paga.

Todas as combinações documentadas estão em `src/granatech_webhook/enums.py` e
nos fixtures de `tests/fixtures/`.

## Exemplos com curl

Consulta (endpoint único):

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  --data @tests/fixtures/consulta_AWAITING_CLIENT_AUTHORIZATION.json
```

Proposta (endpoint único):

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  --data @tests/fixtures/proposta_PENDING_CONFIRMATION__AGUARDANDO_CONFIRMACAO.json
```

Usando aliases (o tipo é forçado pela rota):

```bash
curl -X POST https://SEU-DOMINIO/webhooks/granatech/consultas \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/consulta_SUCCESS.json

curl -X POST https://SEU-DOMINIO/webhooks/granatech/propostas \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/proposta_PAYED__PAGO.json
```

> **Recomendação:** prefira sempre o token no header. A URL com `?token=`
> pode aparecer em logs do Traefik/Dokploy. O suporte à query string existe
> apenas para parceiros que só conseguem configurar a URL.

Com token na query string:

```bash
curl -X POST "https://SEU-DOMINIO/webhooks/granatech?token=SEU_TOKEN" \
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
  IP, rota, hash único, processado/erro/status_conhecido)
- `granatech_consultas` — estado atual por `id_solicitacao`
- `granatech_propostas` — estado atual por `id_proposta`
- `granatech_propostas_historico` — uma linha por notificação de proposta

O evento bruto é sempre gravado primeiro, em transação própria. Depois o
upsert + histórico acontece em outra transação. Se o processamento falhar, o
evento é marcado com erro e a resposta é `500`.

Quando uma consulta traz `id_proposta`, o CPF é copiado para a proposta se ela
existir e ainda não tiver CPF. Ao criar a proposta, o CPF é buscado na consulta
associada.

## Testes

```bash
uv run pytest -q
```

Os testes usam SQLite em memória (`StaticPool`), sobrescrevem `get_db` e não
tocam no `granatech_webhook.db` real. Cobrem todos os fixtures de consulta e
proposta, idempotência, status desconhecido, 422/400, token, allowlist, IP via
proxy, normalização de URL PostgreSQL e LGPD nos logs.

## Docker local

```bash
docker build -t granatech-webhook .
docker run --rm -p 8000:8000 --env-file .env granatech-webhook
curl http://127.0.0.1:8000/health
```

O Dockerfile é multi-stage, usa `uv` com `uv.lock`, roda como usuário não-root,
expõe a porta 8000 e tem `HEALTHCHECK` sem depender de `curl`. O access log do
uvicorn fica desligado para não registrar `?token=`; o log por evento continua
sendo emitido pela aplicação.

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
5. O entrypoint aplica as migrações antes de subir o uvicorn. Em um primeiro
   deploy contra o banco antigo, ele faz `stamp 0001_baseline` automaticamente
   e depois `upgrade head`.

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
endpoint fica público na internet.

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

### URL a cadastrar na Granatech

Recomendado (endpoint único, detecta o tipo pelo campo `tipo`):

```
https://SEU-DOMINIO/webhooks/granatech
```

Alternativas, se a Granatech exigir URLs separadas:

```
https://SEU-DOMINIO/webhooks/granatech/consultas
https://SEU-DOMINIO/webhooks/granatech/propostas
```

Envie o token combinado **no header** configurado. A URL com
`?token=SEU_TOKEN` continua funcionando como compatibilidade, mas não é
recomendada porque pode vazar em logs do Traefik/Dokploy.

## LGPD e logs

- CPF completo **nunca** é logado (nem em mensagens de erro de validação).
  Quando necessário, use o formato mascarado `331.***.***-41`.
- O valor do token nunca é gravado nos headers do evento (fica `"***"`).
- A query string não é gravada em `rota` e o access log do uvicorn é desligado.
- Logs em stdout, uma linha por evento, com timestamp e nível:

```text
2026-11-04 12:00:00,000 INFO granatech_webhook.routers.webhooks evento tipo=consulta id=... status=SUCCESS tipo_notificacao=- evento_id=42 duplicado=não
```

## Pendências a confirmar com a Granatech

- Mecanismo de autenticação/assinatura do webhook (token? HMAC? qual header?).
- Se usam uma URL única ou URLs separadas para consulta e proposta.
- Política de retentativa: quantas vezes, intervalo e quais códigos HTTP
  disparam reenvio.
- Payload exato das notificações "consulta-saldo pronta" e "proposta finalizada
  nos terceiros" (a documentação cita, mas não mostra exemplo).
- IPs de origem para a allowlist (`ALLOWED_IPS`), considerando o proxy.

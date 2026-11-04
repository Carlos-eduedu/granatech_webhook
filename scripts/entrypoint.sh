#!/bin/sh
set -eu

# Aplica migrações (com stamp automático em banco criado pelo create_all).
python -m granatech_webhook.migrate

exec uvicorn granatech_webhook.web.application:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-access-log

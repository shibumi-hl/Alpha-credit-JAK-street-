#!/usr/bin/env bash
# Деплой песочницы на VPS: сборка фронта, архив релиза (код API и движка, демо-компании, фронт, модель), загрузка по
# ssh, установка, проверка по HTTPS.
#
#   bash scripts/deploy.sh           # DEPLOY_HOST, DEPLOY_DOMAIN, DEPLOY_KEY, ENGINE_PATH - из окружения или .env
#   bash scripts/deploy.sh --setup   # первый раз: python3-venv, пользователь, каталоги, import в Caddyfile
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${DEPLOY_HOST:?DEPLOY_HOST, например root@1.2.3.4}" "${DEPLOY_DOMAIN:?DEPLOY_DOMAIN, например credit.example.ru}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/ana_deploy}"
ENGINE="${ENGINE_PATH:-data/scoring/engine.pkl}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes "$DEPLOY_HOST")
[ -f "$ENGINE" ] || { echo "нет $ENGINE - сначала py scripts/train_scorecard.py" >&2; exit 1; }

if [ "${1:-}" = "--setup" ]; then
  echo "→ настройка $DEPLOY_HOST для $DEPLOY_DOMAIN"
  "${SSH[@]}" "bash -s -- $DEPLOY_DOMAIN" < deploy/setup.sh
fi

echo "→ сборка фронта"
# npm ci удаляет node_modules - на Windows это падает, пока запущен Vite; ставим зависимости, только если их нет
if [ ! -x web/node_modules/.bin/vite ]; then (cd web && npm ci --no-audit --no-fund); fi
(cd web && npm run build)

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/release/app"
cp -r api scoring config demo "$STAGE/release/app/"
find "$STAGE/release/app" -name __pycache__ -prune -exec rm -rf {} +
cp -r web/dist "$STAGE/release/web"
cp -r deploy "$STAGE/release/deploy"
cp "$ENGINE" "$STAGE/release/engine.pkl"
tar -czf "$STAGE/release.tgz" -C "$STAGE/release" .  # только относительные пути: GNU tar читает «C:\…» как хост

echo "→ загрузка и установка на $DEPLOY_HOST"
"${SSH[@]}" 'rm -rf /opt/alfa-credit/next && mkdir -p /opt/alfa-credit/next && tar -xzf - -C /opt/alfa-credit/next && bash /opt/alfa-credit/next/deploy/install.sh' < "$STAGE/release.tgz"

echo "→ проверка https://$DEPLOY_DOMAIN"
for _ in $(seq 1 30); do
  if curl -fsS "https://$DEPLOY_DOMAIN/api/health" >/dev/null 2>&1; then
    echo "✓ https://$DEPLOY_DOMAIN"
    exit 0
  fi
  sleep 2  # сертификат Let's Encrypt для нового домена приходит не сразу
done
echo "✗ https://$DEPLOY_DOMAIN/api/health не ответил" >&2
exit 1

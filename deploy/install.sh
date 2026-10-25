#!/usr/bin/env bash
# Ставит загруженный релиз из /opt/alfa-credit/next и перезапускает API. Запускает scripts/deploy.sh.
set -euo pipefail

NEXT=/opt/alfa-credit/next
DOMAIN="$(cat /etc/alfa-credit/domain)"
SITE=/etc/caddy/sites/alfa-credit.caddy

# зависимости - только когда изменился список точных версий
if ! cmp -s "$NEXT/deploy/requirements-server.txt" /opt/alfa-credit/requirements.txt; then
  /opt/alfa-credit/venv/bin/pip install -q --no-cache-dir --disable-pip-version-check -r "$NEXT/deploy/requirements-server.txt"
  install -m 644 "$NEXT/deploy/requirements-server.txt" /opt/alfa-credit/requirements.txt
fi

rm -rf /opt/alfa-credit/app.new /opt/alfa-credit/web.new /opt/alfa-credit/app.old /opt/alfa-credit/web.old
cp -r "$NEXT/app" /opt/alfa-credit/app.new
cp -r "$NEXT/web" /opt/alfa-credit/web.new
chmod -R a+rX /opt/alfa-credit/app.new /opt/alfa-credit/web.new
install -o alfacredit -g alfacredit -m 640 "$NEXT/engine.pkl" /var/lib/alfa-credit/engine.pkl
mv /opt/alfa-credit/app /opt/alfa-credit/app.old && mv /opt/alfa-credit/app.new /opt/alfa-credit/app
mv /opt/alfa-credit/web /opt/alfa-credit/web.old && mv /opt/alfa-credit/web.new /opt/alfa-credit/web

install -m 644 "$NEXT/deploy/alfa-credit.service" /etc/systemd/system/alfa-credit.service
# сайт Caddy: при ошибке в конфиге возвращаем прошлый файл, чтобы не сломать перезагрузку Caddy для Аны
[ -f "$SITE" ] && cp "$SITE" "$SITE.bak"
sed "s/{DOMAIN}/$DOMAIN/g" "$NEXT/deploy/alfa-credit.caddy" > "$SITE"
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
  if [ -f "$SITE.bak" ]; then mv "$SITE.bak" "$SITE"; else rm -f "$SITE"; fi
  echo "caddy config is invalid, site file restored" >&2
  exit 1
fi
rm -f "$SITE.bak"

systemctl daemon-reload
systemctl enable alfa-credit >/dev/null
systemctl restart alfa-credit
systemctl reload caddy || systemctl restart caddy
rm -rf "$NEXT" /opt/alfa-credit/app.old /opt/alfa-credit/web.old

for _ in $(seq 1 90); do  # модель грузится несколько секунд: optbinning тянет ortools и cvxpy
  if curl -fsS http://127.0.0.1:3100/api/health >/dev/null 2>&1; then
    echo "alfa-credit is up on https://$DOMAIN"
    exit 0
  fi
  sleep 1
done
echo "alfa-credit did not start:" >&2
journalctl -u alfa-credit -n 60 --no-pager >&2
exit 1

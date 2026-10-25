#!/usr/bin/env bash
# Разовая настройка VPS под песочницу кредита (Ubuntu 24.04, Caddy уже стоит - его ставит «Легко с Ana»).
# Повторный запуск безопасен. Запуск (root): bash setup.sh <domain> [<прежние адреса через запятую - редирект на domain>]
set -euo pipefail

DOMAIN="${1:?usage: setup.sh <domain> [aliases]}"
ALIASES="${2:-}"
export DEBIAN_FRONTEND=noninteractive

if ! dpkg -s python3-venv >/dev/null 2>&1; then
  apt-get update -q
  apt-get install -y -q python3-venv
fi

# Системный пользователь без шелла; сервис только читает код и модель
id alfacredit >/dev/null 2>&1 || useradd --system --home-dir /var/lib/alfa-credit --shell /usr/sbin/nologin alfacredit
install -d -o root -g root -m 755 /opt/alfa-credit /opt/alfa-credit/app /opt/alfa-credit/web /etc/alfa-credit /etc/caddy/sites
install -d -o alfacredit -g alfacredit -m 750 /var/lib/alfa-credit
echo "$DOMAIN" > /etc/alfa-credit/domain
echo "$ALIASES" > /etc/alfa-credit/aliases
[ -x /opt/alfa-credit/venv/bin/python ] || python3 -m venv /opt/alfa-credit/venv

# Наш сайт - отдельным файлом в /etc/caddy/sites. install.sh Аны перезаписывает /etc/caddy/Caddyfile из своего
# шаблона, поэтому та же строка import стоит и в шаблоне ana_bot/deploy/Caddyfile.
grep -qxF 'import /etc/caddy/sites/*.caddy' /etc/caddy/Caddyfile || printf '\nimport /etc/caddy/sites/*.caddy\n' >> /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

echo "setup done for $DOMAIN"

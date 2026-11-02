# Mihomo — выделенный прокси-сервер с веб-панелью

Стек: `metacubex/mihomo` (Clash Meta) + веб-панель **zashboard**.
Отдельный от mihomo внутри контейнера devin — этот для внешних клиентов.
Развёрнут на хосте в `/docker/mihomo`; здесь — его копия под версией
(без секретов: живой `config.yaml` с ключами не коммитим).

## Быстрый старт

```bash
cd /docker/mihomo
# 1. Впиши свои ноды в config/config.yaml → секция proxies:
nano config/config.yaml
# 2. Запуск
docker compose up -d
```

## Доступы

| Что | Куда | Авторизация |
|-----|------|-------------|
| Веб-панель | https://mihomo.ai.kilop.ru/ui | `secret` из config.yaml |
| REST API | http://<IP>:9090 | тот же `secret` |
| Прокси (HTTP+SOCKS5) | `<IP>:7890` | `authentication:` из config.yaml |

Подключение клиентов к прокси:
```
http://vpn:<пароль>@<IP-сервера>:7890
socks5://vpn:<пароль>@<IP-сервера>:7890
```
Текущие логин/пароль и secret — в `config/config.yaml` на хосте
(поля `authentication` и `secret`, сгенерированы случайно — поменяй на свои).

## Веб-панель (zashboard)

- Открывается по `https://mihomo.ai.kilop.ru/ui` (Traefik, TLS от Let's Encrypt).
- При первом входе панель спросит backend: укажи
  `https://mihomo.ai.kilop.ru` и secret из конфига — запомнит сама.
- Через панель: выбор ноды в группе «Прокси», замер задержек,
  живые соединения, логи, редактирование конфига, режимы rule/global/direct.
- Замена панели: положи другой дашборд (metacubexd, yacd) в `config/ui/`
  (zashboard v3.30.0 уже разложен туда на хосте).

## Как прокинуть свой конфиг

Конфиг — `config/config.yaml`, проброшен в контейнер целиком.

- Вставь ноды в `proxies:` (формат Clash/Mihomo — секция из конфига
  подписки подходит как есть). Группа `Прокси` подхватит их сама
  (`include-all`).
- **НЕ трогай** блоки `external-controller`, `external-ui`, `secret` —
  без них панель умрёт. Если вставляешь конфиг подписки целиком,
  удали из него `tun:`, `redir-port`, `sniffer:` — в Docker они не нужны
  (TUN требует NET_ADMIN и /dev/net/tun).
- НЕ удаляй `authentication` — порт 7890 смотрит в интернет.
- После правки: `docker compose restart` (или `docker restart mihomo`).

## Порты на хосте

- `7890/tcp+udp` — mixed-прокси наружу (auth обязателен!)
- `9090/tcp` — API + `/ui`; открыт на 0.0.0.0 для Traefik
  (`mihomo.ai.kilop.ru` → host.docker.internal:9090 в
  `/docker/traefik/dynamic.yml`). Наружу ходи через HTTPS-домен.

## Команды

```bash
docker compose up -d          # запуск
docker compose restart        # применить новый config.yaml
docker compose logs -f        # логи
docker exec mihomo mihomo -v  # версия ядра
```

Проверка прокси с хоста:
```bash
curl -x http://vpn:<пароль>@127.0.0.1:7890 https://api.ipify.org
curl -x http://127.0.0.1:7890 https://api.ipify.org   # → 407, если auth стоит
```

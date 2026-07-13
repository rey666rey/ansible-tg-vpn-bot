# Server Ansible Only

Ansible-playbook для первичной настройки VPS и установки 3x-ui.

Что делает `server_tuning.yml`:

- создает администратора, по умолчанию `rey`;
- добавляет SSH-ключ `rey_server_ed25519.pub`;
- включает passwordless sudo для администратора;
- настраивает sysctl/network tuning, BBR и IP forwarding;
- устанавливает 3x-ui;
- настраивает 3 inbound: VLESS Reality, VLESS XHTTP TLS и Hysteria2;
- включает UFW и Fail2Ban;
- закрывает root SSH login в конце успешного запуска.

## Требования

На локальной машине:

- Ansible;
- SSH-клиент;
- `sshpass`, если подключаешься по паролю через `ROOT_PASSWORD` или `SERVER_PASSWORD`.

На сервере:

- Debian/Ubuntu-подобная система;
- доступ по SSH от root для первого запуска;
- Python 3 на сервере, либо возможность установить его пакетным менеджером;
- домен, который уже указывает A/AAAA-записью на этот сервер.

Для macOS Ansible можно поставить так:

```bash
brew install ansible sshpass
```

Если `sshpass` не ставится через Homebrew, удобнее запускать по SSH-ключу.

## Быстрый запуск

1. Скопируй примеры конфигов:

```bash
cp .env.example .env
```

2. Заполни `.env`.

Минимально нужны:

```bash
ADMIN_USER=rey
ADMIN_USER_PASSWORD='rey-user-password'

SERVER_HOSTS="203.0.113.10"
SERVER_USER=root
SERVER_PORT=22
ROOT_PASSWORD=ROOT_PASSWORD_FOR_FIRST_BOOTSTRAP_ONLY
ANSIBLE_HOST_KEY_CHECKING=False

XUI_USERNAME=rey
XUI_PASSWORD=XUI_PANEL_PASSWORD
XUI_API_TOKEN_NAME=ansible
XUI_TLS_DOMAIN=fi.reyreyrey.space
XUI_PANEL_DOMAIN=reyreyrey.space
XUI_PANEL_PORT=24444
XUI_SUBSCRIPTION_PORT=2096
XUI_SUBSCRIPTION_PATH=/subrey/
XUI_CLASH_SUBSCRIPTION_PATH=/clashrey/
XUI_REALITY_TARGET=www.microsoft.com:443
XUI_REALITY_SERVER_NAME=www.microsoft.com
XUI_REALITY_SELF_TEST=true
XUI_ACME_EMAIL=mail@example.com
XUI_MANAGE_INBOUNDS=true
```

Если в пароле есть спецсимволы (`$`, `!`, пробелы, `#`), оберни значение в одинарные кавычки.

`ADMIN_USER_PASSWORD` - это обычный пароль Linux-пользователя `ADMIN_USER`, по умолчанию `rey`.

Если не хочешь хранить обычный пароль, можно вместо него указать готовый SHA-512 crypt hash:

```bash
ADMIN_USER_PASSWORD_HASH='$6$replace-with-your-sha512-crypt-hash'
```

Сгенерировать hash можно командой:

```bash
openssl passwd -6
```

3. Для нескольких серверов укажи их через пробел или запятую:

```bash
SERVER_HOSTS="203.0.113.10 203.0.113.11"
# или
SERVER_HOSTS="203.0.113.10,203.0.113.11"
```

4. Проверь права на приватный ключ и скрипт:

```bash
cp rey_server_ed25519.pub.example rey_server_ed25519.pub
# замени содержимое rey_server_ed25519.pub на свой настоящий публичный ключ
chmod 600 rey_server_ed25519
chmod 700 run-playbook.sh
```

Для запуска через systemd удобнее положить публичный ключ прямо в `.env`:

```bash
ADMIN_SSH_PUBLIC_KEY='ssh-ed25519 AAAA... your-key-comment'
```

или указать путь к файлу:

```bash
ADMIN_SSH_PUBLIC_KEY_FILE=/opt/server-tg-bot/rey_server_ed25519.pub
```

5. Запусти playbook:

```bash
./run-playbook.sh
```

Скрипт сам загрузит `.env` и выполнит:

```bash
ansible-playbook -i .ansible/generated-inventory.ini server_tuning.yml
```

Если `SERVER_HOSTS` не задан, скрипт использует старый ручной файл `inventory.ini`.

В конце успешного запуска playbook выведет API token для 3x-ui:

```text
XUI_API_TOKEN_NAME=ansible
XUI_API_TOKEN=...
XUI_API_AUTH_HEADER=Authorization: Bearer ...
```

Этот token сохраняется на сервере в `/etc/x-ui/ansible-api-token.env` с правами `0600`. При повторном запуске playbook вернет тот же token.

## Первый и повторные запуски

Первый запуск лучше делать от `root`, потому что playbook:

- создает пользователя `ADMIN_USER`;
- добавляет ему SSH-ключ;
- проверяет sudo;
- включает firewall;
- только после этого отключает root login по SSH.

После первого успешного запуска поменяй подключение на администратора:

```bash
SERVER_USER=rey
SERVER_PASSWORD=REY_PASSWORD
```

Или используй SSH-ключ:

```bash
SERVER_USER=rey
SERVER_SSH_PRIVATE_KEY_FILE=./rey_server_ed25519
# ROOT_PASSWORD можно убрать или закомментировать
```

Если используешь ключ без пароля, `SERVER_PASSWORD` не нужен.

## Запуск с дополнительными параметрами

Любые аргументы после `./run-playbook.sh` передаются в `ansible-playbook`.

Пример syntax-check:

```bash
./run-playbook.sh --syntax-check
```

Пример dry-run:

```bash
./run-playbook.sh --check
```

Пример переопределения переменной:

```bash
./run-playbook.sh -e xui_manage_inbounds=false
```

## Важные переменные

Основные переменные задаются в `.env`:

| Переменная | Для чего |
| --- | --- |
| `ADMIN_USER` | Linux-пользователь, которого создаст playbook. По умолчанию `rey`. |
| `ADMIN_USER_PASSWORD` | Обычный пароль Linux-пользователя `ADMIN_USER`. |
| `ADMIN_USER_PASSWORD_HASH` | Опционально: готовый hash пароля в формате SHA-512 crypt вместо `ADMIN_USER_PASSWORD`. |
| `SERVER_HOSTS` | IP-адреса или домены серверов через пробел или запятую. |
| `SERVER_USER` | Пользователь, от которого Ansible подключается к серверу. Для первого запуска обычно `root`. |
| `SERVER_PORT` | SSH-порт. По умолчанию `22`. |
| `ROOT_PASSWORD` | Root-пароль для первого запуска. Используется только когда `SERVER_USER=root`. |
| `SERVER_PASSWORD` | SSH-пароль для повторных запусков, если подключаешься не root-пользователем. |
| `SERVER_SSH_PRIVATE_KEY_FILE` | Путь к приватному SSH-ключу, если подключаешься ключом. |
| `ANSIBLE_HOST_KEY_CHECKING` | Проверка SSH host key. Для первого password-запуска удобно `False`. |
| `XUI_USERNAME` | Логин панели 3x-ui. |
| `XUI_PASSWORD` | Пароль панели 3x-ui. |
| `XUI_API_TOKEN_NAME` | Имя API token в 3x-ui. По умолчанию `ansible`. |
| `XUI_TLS_DOMAIN` | Домен для TLS-сертификатов inbound-ов и подписок, например `fi.reyreyrey.space`. |
| `XUI_PANEL_DOMAIN` | Домен панели, например `reyreyrey.space`. Если не задан, используется `XUI_TLS_DOMAIN`. |
| `XUI_PANEL_PORT` | Порт панели и API 3x-ui. По умолчанию `24444`. |
| `XUI_PANEL_BASE_PATH` | Обычно не нужен: Telegram-бот генерит случайный base path при первой раскатке и сохраняет его в sqlite. |
| `XUI_SUBSCRIPTION_PORT` | Порт подписок. По умолчанию `2096`. |
| `XUI_SUBSCRIPTION_PATH` | Путь обычной подписки. По умолчанию `/subrey/`. |
| `XUI_CLASH_SUBSCRIPTION_PATH` | Путь Clash/Mihomo подписки. По умолчанию `/clashrey/`. |
| `XUI_REALITY_TARGET` | TLS-сайт для маскировки Reality, например `www.microsoft.com:443`. |
| `XUI_REALITY_SERVER_NAME` | SNI для Reality. Обычно домен из `XUI_REALITY_TARGET` без порта. |
| `XUI_REALITY_SELF_TEST` | После раскатки запускать настоящий локальный xray-клиент через Reality. По умолчанию `true`. |
| `XUI_ACME_EMAIL` | Email для ACME/Let's Encrypt. Можно оставить пустым, но лучше указать. |
| `XUI_MANAGE_INBOUNDS` | Создавать TLS inbound-ы и выпускать сертификат. По умолчанию `true`. |

Если `SERVER_HOSTS` задан, `run-playbook.sh` генерирует inventory автоматически в `.ansible/generated-inventory.ini`. Если `SERVER_HOSTS` не задан, используется ручной `inventory.ini`.

В самом playbook также есть параметры по умолчанию:

| Переменная | Значение |
| --- | --- |
| `xui_panel_port` | `24444` |
| `xui_web_base_path` | генерируется ботом при раскатке |
| `xui_subscription_port` | `2096` |
| `xui_subscription_path` | `/subrey/` |
| `xui_clash_subscription_path` | `/clashrey/` |
| `xui_reality_port` | `8443` |
| `xui_reality_target` | `www.microsoft.com:443` |
| `xui_reality_server_name` | `www.microsoft.com` |
| `xui_xhttp_port` | `443` |
| `xui_hysteria_port` | `443/udp` |

## Открытые порты

Playbook открывает в UFW:

- `22/tcp` для SSH;
- `80/tcp` для ACME/сертификатов;
- `24444/tcp` для панели и API 3x-ui, чтобы Telegram-бот мог создавать клиентов;
- `2096/tcp` для подписок;
- `8443/tcp` для VLESS Reality;
- `443/tcp` для VLESS XHTTP TLS;
- `443/udp` для Hysteria2.

## Проверка после запуска

Проверить SSH:

```bash
ssh -i ./rey_server_ed25519 rey@203.0.113.10
```

Проверить UFW:

```bash
sudo ufw status
```

Проверить 3x-ui:

```bash
sudo systemctl status x-ui
```

Проверить, что 3x-ui реально применил inbound-ы в runtime и Reality пропускает
трафик, можно тем же скриптом, который запускает playbook:

```bash
sudo /usr/local/sbin/check-3x-ui-inbounds.py
```

Если эта проверка падает на `reality self-test failed`, значит порт может быть
открыт и подписка может генериться, но настоящий VLESS Reality handshake не
проходит. Это специально считается ошибкой раскатки. Временно пропустить только
эту проверку можно через `XUI_REALITY_SELF_TEST=false`, но лучше сначала поменять
`XUI_REALITY_TARGET`/`XUI_REALITY_SERVER_NAME` или версию core.

Проверить API token:

```bash
curl -H "Authorization: Bearer XUI_API_TOKEN" \
  https://reyreyrey.space:24444/<generated-panel-path>/panel/api/server/status
```

Итоговый вид ссылок:

```text
https://reyreyrey.space:24444/<generated-panel-path>/panel/
https://fi.reyreyrey.space:2096/subrey/<random-sub-id>
https://fi.reyreyrey.space:2096/clashrey/<random-sub-id>
```

При раскатке через Telegram-бота можно прислать:

```text
ip=203.0.113.10
domain=fi.reyreyrey.space
panel_domain=reyreyrey.space
```

Если хочешь именно автогенерацию secret path панели, не задавай
`XUI_PANEL_BASE_PATH` в `.env`. Если переменная задана, бот будет использовать ее
как ручной override.

Кнопка `🗑 удалить пользователя` только удаляет клиента из всех inbound-ов на всех
серверах из sqlite и чистит локальную запись клиента в базе бота.

Кнопка `🧨 удалить сервер` удаляет сервер из sqlite бота вместе с локальными
записями клиентов этого сервера. Сам VPS она не трогает. Используй ее перед
повторной раскаткой после reinstall VPS: у переустановленного сервера меняется
SSH host key, а старый xui token из базы уже невалиден.

Проверить Fail2Ban:

```bash
sudo systemctl status fail2ban
```

## запуск telegram-бота как systemd-службы

Пример unit-файла лежит в `systemd/server-tg-bot.service`.

По умолчанию он ожидает:

- проект в `/opt/server-tg-bot`;
- виртуальное окружение в `/opt/server-tg-bot/.venv`;
- `.env` в `/opt/server-tg-bot/.env`;
- запуск от пользователя `rey`.

Если путь или пользователь другие, сначала поправь `User`, `Group`, `WorkingDirectory`,
`EnvironmentFile` и `ExecStart` в `systemd/server-tg-bot.service`.

### первичная установка

На сервере, где будет крутиться бот:

```bash
sudo mkdir -p /opt/server-tg-bot
sudo rsync -a \
  --exclude .git \
  --exclude .venv \
  --exclude data \
  --exclude .env \
  ./ /opt/server-tg-bot/
sudo chown -R rey:rey /opt/server-tg-bot
```

Создай venv и поставь зависимости:

```bash
cd /opt/server-tg-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Поставь системные зависимости для раскатки по SSH-паролю:

```bash
sudo apt update
sudo apt install -y ansible sshpass
ansible-playbook --version
```

Создай локальный `.env` и заполни секреты:

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Минимально нужны `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_IDS`,
`ADMIN_USER_PASSWORD` и `XUI_PASSWORD`.

Поставь службу:

```bash
sudo cp /opt/server-tg-bot/systemd/server-tg-bot.service /etc/systemd/system/server-tg-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now server-tg-bot
```

Проверить статус:

```bash
sudo systemctl status server-tg-bot
```

Смотреть логи:

```bash
journalctl -u server-tg-bot -f
```

Перезапустить после изменения кода или `.env`:

```bash
sudo systemctl restart server-tg-bot
```

Остановить:

```bash
sudo systemctl stop server-tg-bot
```

### обновление кода

После pull/rsync нового кода:

```bash
cd /opt/server-tg-bot
.venv/bin/pip install -r requirements.txt
sudo systemctl restart server-tg-bot
```

## Частые проблемы

### `Missing .env`

Создай `.env` из примера:

```bash
cp .env.example .env
```

### Ошибка про `ADMIN_USER_PASSWORD` или `XUI_PASSWORD`

Playbook требует чувствительные значения из `.env`. Проверь, что переменные заполнены:

```bash
ADMIN_USER_PASSWORD='...'
XUI_PASSWORD='...'
```

### Using a SSH password instead of a key is not possible because Host Key checking is enabled

Для первого запуска по root-паролю добавь в `.env`:

```bash
ANSIBLE_HOST_KEY_CHECKING=False
```

`run-playbook.sh` уже ставит это значение по умолчанию, но строка в `.env` делает поведение явным.

Более строгий вариант - заранее добавить fingerprint сервера:

```bash
ssh-keyscan -H 203.0.113.10 >> ~/.ssh/known_hosts
```

### Invalid/incorrect password или Permission denied

SSH не пустил Ansible на сервер. Обычно это одно из трех:

- после reinstall VPS нужен новый root-пароль от провайдера;
- указан не тот `USER`: для свежего сервера чаще всего нужен `user=root`;
- сервер уже был раскатан раньше, root SSH отключен, и надо заходить под `ADMIN_USER`.

Для свежего reinstall через Telegram-бота отправь:

```text
ip=203.0.113.10
user=root
password=NEW_ROOT_PASSWORD
domain=fi.reyreyrey.space
panel_domain=reyreyrey.space
```

Если в боте уже был старый сервер, сначала нажми `🧨 удалить сервер`, чтобы
убрать старый xui token и локальные записи из sqlite.

### Unable to create local directories(/private/tmp/ansible-local)

Это macos-путь, который не подходит для ubuntu. В `.env` убери старую строку
`ANSIBLE_LOCAL_TEMP=/private/tmp/ansible-local` или замени ее:

```bash
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local
```

После правки перезапусти службу:

```bash
sudo systemctl restart server-tg-bot
```

### TLS certificate was not found

Скорее всего, домен из `XUI_TLS_DOMAIN` не указывает на сервер или порт `80/tcp` недоступен извне.

Важно: просто указать домен в `.env` недостаточно. DNS-запись домена должна вести на IP этого сервера, а Let's Encrypt должен иметь возможность достучаться до сервера по HTTP на внешнем порту `80/tcp`.

Проверь DNS:

```bash
dig +short vpn.example.com
```

Адрес должен совпадать с IP сервера.

Проверь, что порт `80/tcp` открыт у провайдера VPS/security group/firewall. Внутри сервера playbook открывает его в UFW сам.

Если нужно сначала закончить базовую настройку без TLS inbound-ов, временно поставь:

```bash
XUI_MANAGE_INBOUNDS=false
```

Потом поправь DNS/порт 80, верни `XUI_MANAGE_INBOUNDS=true` и запусти `./run-playbook.sh` еще раз.

### Ansible не может подключиться после первого запуска

После успешного первого запуска root SSH отключается. Используй пользователя `rey` или значение из `ADMIN_USER`.

Пример:

```bash
SERVER_USER=rey
SERVER_SSH_PRIVATE_KEY_FILE=./rey_server_ed25519
# или SERVER_PASSWORD=REY_PASSWORD
```

### SSH key passphrase

Ansible не читает passphrase от ключа из `.env`. Добавь ключ в ssh-agent:

```bash
ssh-add ./rey_server_ed25519
```

## Структура проекта

```text
.
├── .env.example
├── inventory.ini.example
├── run-playbook.sh
├── server_tuning.yml
├── rey_server_ed25519
└── rey_server_ed25519.pub
```

`rey_server_ed25519` - приватный ключ. Не публикуй его и не коммить в открытые репозитории.

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
XUI_TLS_DOMAIN=vpn.example.com
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
| `XUI_TLS_DOMAIN` | Домен для TLS-сертификатов и подписок. |
| `XUI_ACME_EMAIL` | Email для ACME/Let's Encrypt. Можно оставить пустым, но лучше указать. |
| `XUI_MANAGE_INBOUNDS` | Создавать TLS inbound-ы и выпускать сертификат. По умолчанию `true`. |

Если `SERVER_HOSTS` задан, `run-playbook.sh` генерирует inventory автоматически в `.ansible/generated-inventory.ini`. Если `SERVER_HOSTS` не задан, используется ручной `inventory.ini`.

В самом playbook также есть параметры по умолчанию:

| Переменная | Значение |
| --- | --- |
| `xui_panel_port` | `2053` |
| `xui_web_base_path` | `rey` |
| `xui_subscription_port` | `2096` |
| `xui_reality_port` | `8443` |
| `xui_xhttp_port` | `443` |
| `xui_hysteria_port` | `443/udp` |

## Открытые порты

Playbook открывает в UFW:

- `22/tcp` для SSH;
- `80/tcp` для ACME/сертификатов;
- `2053/tcp` для панели и API 3x-ui, чтобы Telegram-бот мог создавать клиентов;
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

Проверить API token:

```bash
curl -H "Authorization: Bearer XUI_API_TOKEN" \
  http://vpn.example.com:2053/rey/panel/api/server/status
```

Проверить Fail2Ban:

```bash
sudo systemctl status fail2ban
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

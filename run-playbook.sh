#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and fill it first." >&2
  exit 1
fi

set -a
. ./.env
set +a

export ANSIBLE_LOCAL_TEMP="${ANSIBLE_LOCAL_TEMP:-/private/tmp/ansible-local}"
export ANSIBLE_HOST_KEY_CHECKING="${ANSIBLE_HOST_KEY_CHECKING:-False}"

inventory_file="${ANSIBLE_INVENTORY:-inventory.ini}"

if [ "${SERVER_HOSTS:-}" ]; then
  mkdir -p .ansible
  inventory_file=".ansible/generated-inventory.ini"
  server_user="${SERVER_USER:-root}"
  server_port="${SERVER_PORT:-22}"
  server_key="${SERVER_SSH_PRIVATE_KEY_FILE:-}"

  {
    printf '[xui_servers]\n'
    index=1
    normalized_hosts="${SERVER_HOSTS//,/ }"
    for host in ${normalized_hosts}; do
      printf 'server%s ansible_host=%s ansible_user=%s ansible_port=%s' "$index" "$host" "$server_user" "$server_port"
      if [ "$server_key" ]; then
        printf ' ansible_ssh_private_key_file=%s' "$server_key"
      fi
      printf '\n'
      index=$((index + 1))
    done
    if [ "$index" -eq 1 ]; then
      echo "SERVER_HOSTS is set but no hosts were found." >&2
      exit 1
    fi
    printf '\n[xui_servers:vars]\n'
    printf 'ansible_become=true\n'
    printf 'ansible_python_interpreter=/usr/bin/python3\n'
  } > "$inventory_file"
fi

extra_args=()
if [ -z "${SERVER_HOSTS:-}" ] && [ "${ANSIBLE_USER:-}" ]; then
  extra_args+=("-e" "ansible_user=${ANSIBLE_USER}")
fi
connection_password=""
if [ "${SERVER_PASSWORD:-}" ]; then
  connection_password="$SERVER_PASSWORD"
elif [ "${SERVER_HOSTS:-}" ] && [ "${server_user:-root}" = "root" ] && [ "${ROOT_PASSWORD:-}" ]; then
  connection_password="$ROOT_PASSWORD"
elif [ -z "${SERVER_HOSTS:-}" ] && [ "${ANSIBLE_PASSWORD:-}" ]; then
  connection_password="$ANSIBLE_PASSWORD"
fi
if [ "$connection_password" ]; then
  extra_args+=("-e" "ansible_password=${connection_password}")
fi

ansible-playbook -i "$inventory_file" server_tuning.yml "${extra_args[@]}" "$@"

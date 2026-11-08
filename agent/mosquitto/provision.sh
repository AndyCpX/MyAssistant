#!/usr/bin/env bash
# Configura il broker MQTT di JARVIS: un ruolo per scheda, con i soli topic suoi, e un utente per ciascuna.
# Uso (dalla cartella agent/, con il broker avviato e dynsec inizializzato):
#   bash mosquitto/provision.sh <password-admin> <password-notify> kitchen:<pw> bedroom:<pw> ...
# Default: tutto negato. Ogni scheda legge solo jarvis/notify/<id> e scrive solo jarvis/ack/<id>.
# Nota: in dynamic-security il %u funziona per la pubblicazione ma non per la sottoscrizione letterale,
# quindi i topic sono scritti per esteso.
set -eu
[ $# -ge 3 ] || { echo "uso: $0 <admin> <notify> <device:password>..." >&2; exit 1; }
ADMIN_PW="$1"; NOTIFY_PW="$2"; shift 2
export MSYS_NO_PATHCONV=1   # Git Bash su Windows: non trasformare i percorsi

# Esegue un comando dynsec: mostra gli errori, ignora i messaggi di avviso di mosquitto_ctrl.
ctl() {
  local out
  out=$(docker compose exec -T mqtt mosquitto_ctrl -u admin -P "$ADMIN_PW" dynsec "$@" 2>&1 | grep -viE "^Warning|encryption|visible" || true)
  if echo "$out" | grep -qiE "error|fail|unable"; then echo "ATTENZIONE dynsec $*: $out" >&2; fi
}

ctl setDefaultACLAccess subscribe deny
ctl setDefaultACLAccess publishClientSend deny
ctl deleteRole device   # ruolo condiviso della versione precedente: sostituito dai ruoli per scheda

ctl createRole notify
ctl addRoleACL notify subscribePattern "jarvis/ack/#" allow 1
ctl addRoleACL notify publishClientSend "jarvis/notify/#" allow 1
ctl createClient notify -p "$NOTIFY_PW"
ctl addClientRole notify notify

for pair in "$@"; do
  dev="${pair%%:*}"; pw="${pair#*:}"
  ctl createRole "dev-$dev"
  ctl addRoleACL "dev-$dev" subscribeLiteral "jarvis/notify/$dev" allow 1
  ctl addRoleACL "dev-$dev" publishClientSend "jarvis/ack/$dev" allow 1
  ctl createClient "$dev" -p "$pw"
  ctl addClientRole "$dev" "dev-$dev"
  echo "scheda configurata: $dev"
done
echo "broker configurato. Il servizio notify usa MQTT_USER=notify con la password indicata."

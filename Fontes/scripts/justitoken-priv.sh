#!/bin/sh
# justitoken-priv.sh - Ajudante privilegiado do JustiToken no Linux.
#
# Concentra TODAS as operacoes que exigem root em um unico script, com os
# argumentos validados. Assim o programa pede a senha UMA vez por acao (pkexec)
# e, se o administrador quiser, pode liberar so este script no sudoers
# (o instalar.sh oferece isso), sem dar acesso root geral.
#
# Uso: justitoken-priv.sh <acao> [argumentos]
#   servidor-preparar | bind BUSID | unbind BUSID | rebind BUSID
#   cliente-preparar  | attach HOST BUSID | detach PORTA
#   firewall | instalar-pacotes

set -u
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

acao="${1:-}"
[ $# -gt 0 ] && shift

valida_busid() { printf '%s' "$1" | grep -Eq '^[0-9]+-[0-9]+(\.[0-9]+)*$' || { echo "busid invalido: $1" >&2; exit 2; }; }
valida_host()  { printf '%s' "$1" | grep -Eq '^[A-Za-z0-9._:-]{1,253}$'   || { echo "host invalido: $1" >&2; exit 2; }; }
valida_porta() { printf '%s' "$1" | grep -Eq '^[0-9]{1,3}$'               || { echo "porta invalida: $1" >&2; exit 2; }; }

# O binario "usbip" no Ubuntu/Debian pode estar em /usr/lib/linux-tools/<kernel>/
acha() {
    command -v "$1" 2>/dev/null && return 0
    for d in /usr/lib/linux-tools/*/"$1" /usr/lib/linux-tools-*/"$1"; do
        [ -x "$d" ] && { echo "$d"; return 0; }
    done
    return 1
}

servidor_preparar() {
    modprobe usbip-core 2>/dev/null
    modprobe usbip-host || { echo "modulo usbip-host indisponivel neste kernel" >&2; exit 3; }
    if ! pgrep -x usbipd >/dev/null 2>&1; then
        d=$(acha usbipd) || { echo "usbipd nao instalado" >&2; exit 4; }
        "$d" -D || exit 5
    fi
}

case "$acao" in
    servidor-preparar)
        servidor_preparar ;;
    bind)
        valida_busid "${1:-}"; servidor_preparar
        u=$(acha usbip) || { echo "usbip nao instalado" >&2; exit 4; }
        "$u" bind -b "$1" ;;
    unbind)
        valida_busid "${1:-}"
        u=$(acha usbip) || { echo "usbip nao instalado" >&2; exit 4; }
        "$u" unbind -b "$1" ;;
    rebind)
        valida_busid "${1:-}"; servidor_preparar
        u=$(acha usbip) || { echo "usbip nao instalado" >&2; exit 4; }
        "$u" unbind -b "$1"
        sleep 1
        "$u" bind -b "$1" ;;
    cliente-preparar)
        modprobe vhci-hcd || { echo "modulo vhci-hcd indisponivel neste kernel" >&2; exit 3; } ;;
    attach)
        valida_host "${1:-}"; valida_busid "${2:-}"
        modprobe vhci-hcd || { echo "modulo vhci-hcd indisponivel neste kernel" >&2; exit 3; }
        u=$(acha usbip) || { echo "usbip nao instalado" >&2; exit 4; }
        "$u" attach -r "$1" -b "$2" ;;
    detach)
        valida_porta "${1:-}"
        u=$(acha usbip) || { echo "usbip nao instalado" >&2; exit 4; }
        "$u" detach -p "$1" ;;
    firewall)
        if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
            ufw allow 3240/tcp && ufw allow 3241/tcp
        elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
            firewall-cmd --permanent --add-port=3240/tcp --add-port=3241/tcp && firewall-cmd --reload
        else
            echo "nenhum firewall ativo (ufw/firewalld); nada a fazer"
        fi ;;
    instalar-pacotes)
        if   command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq
            apt-get install -y usbip hwdata || apt-get install -y linux-tools-generic linux-tools-common hwdata
        elif command -v dnf >/dev/null 2>&1;     then dnf install -y usbip
        elif command -v pacman >/dev/null 2>&1;  then pacman -S --noconfirm usbip
        elif command -v zypper >/dev/null 2>&1;  then zypper --non-interactive install usbip-utils || zypper --non-interactive install usbip
        else echo "gerenciador de pacotes nao reconhecido; instale o pacote 'usbip' manualmente" >&2; exit 6
        fi ;;
    *)
        echo "uso: $0 {servidor-preparar|bind|unbind|rebind|cliente-preparar|attach|detach|firewall|instalar-pacotes}" >&2
        exit 64 ;;
esac

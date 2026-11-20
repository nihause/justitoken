#!/usr/bin/env bash
# instalar.sh - Instalador do JustiToken / USB pela Rede para Linux.
# Uso: ./instalar.sh
set -u
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONTES="$RAIZ/Fontes"
VENV="$RAIZ/.venv"
PRIV_ORIGEM="$FONTES/scripts/justitoken-priv.sh"
PRIV_DESTINO="/usr/local/lib/justitoken/priv.sh"

py() { if [ -x "$VENV/bin/python" ]; then "$VENV/bin/python" "$@"; else python3 "$@"; fi; }
pausa() { echo; read -r -p "Enter para continuar..." _; }

passo_deps() {
    echo "Instalando Python, Tk e bibliotecas (interface)..."
    if   command -v apt-get >/dev/null; then sudo apt-get install -y python3 python3-venv python3-tk gir1.2-ayatanaappindicator3-0.1 gvfs-backends 2>/dev/null || sudo apt-get install -y python3 python3-venv python3-tk gvfs-backends
    elif command -v dnf >/dev/null;     then sudo dnf install -y python3 python3-tkinter gvfs-fuse
    elif command -v pacman >/dev/null;  then sudo pacman -S --needed --noconfirm python tk gvfs
    elif command -v zypper >/dev/null;  then sudo zypper install -y python3 python3-tk gvfs-backends
    else echo "Gerenciador de pacotes nao reconhecido: instale python3, tkinter e venv manualmente."; fi
    # --system-site-packages: deixa o venv enxergar pacotes do sistema (ex.: appindicator da bandeja)
    python3 -m venv --system-site-packages "$VENV" || { echo "Falha ao criar o ambiente virtual."; return; }
    "$VENV/bin/pip" install --upgrade pip
    "$VENV/bin/pip" install -r "$FONTES/requirements.txt" && echo "Bibliotecas instaladas em $VENV"
}

passo_motor() {
    echo "Instalando o pacote usbip (ferramentas USB/IP do kernel)..."
    sudo sh "$PRIV_ORIGEM" instalar-pacotes
    if command -v usbip >/dev/null || ls /usr/lib/linux-tools/*/usbip >/dev/null 2>&1; then
        echo "usbip instalado."
    else
        echo "Nao consegui confirmar o usbip. No Ubuntu/Debian: sudo apt install linux-tools-generic hwdata"
    fi
    echo "Modulos do kernel: servidor usa 'usbip-host', estacao usa 'vhci-hcd'."
    # Carrega no boot (ambos; sao leves)
    printf 'usbip-core\nusbip-host\nvhci-hcd\n' | sudo tee /etc/modules-load.d/justitoken.conf >/dev/null
}

passo_sudoers() {
    echo "Isto instala o ajudante em $PRIV_DESTINO (dono root) e libera SO ele no sudoers"
    echo "para o usuario '$USER', sem senha. O ajudante valida os argumentos; ele so"
    echo "faz bind/unbind/attach/detach de USB e libera as portas 3240/3241."
    read -r -p "Confirma? (s/N) " r
    [ "$r" = "s" ] || [ "$r" = "S" ] || return
    sudo install -d -o root -g root -m 755 /usr/local/lib/justitoken
    sudo install -o root -g root -m 755 "$PRIV_ORIGEM" "$PRIV_DESTINO"
    echo "$USER ALL=(root) NOPASSWD: $PRIV_DESTINO" | sudo tee /etc/sudoers.d/justitoken >/dev/null
    sudo chmod 440 /etc/sudoers.d/justitoken
    sudo visudo -cf /etc/sudoers.d/justitoken && echo "Pronto: o programa nao pedira mais senha para as acoes USB."
}

passo_autostart() {  # $1 = servidor|estacao
    local alvo="$RAIZ/usb-$1.sh"
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/justitoken-$1.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=JustiToken $1
Exec="$alvo"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    echo "Este PC inicia o $1 junto com a sessao."
}

while true; do
    clear
    cat <<EOF
============================================================
       USB PELA REDE  -  INSTALADOR LINUX
============================================================
  Pasta: $RAIZ

  --- Passo 1 ---
  [1] Instalar Python/Tk e bibliotecas (1x por PC)
  --- Passo 2 ---
  [2] Instalar o motor USB/IP (pacote usbip + modulos do kernel)
  [3] (opcional) Nao pedir senha a cada acao USB (sudoers restrito)
  --- Passo 3 ---
  [4] Este PC sera SERVIDOR (inicia com a sessao)
  [5] Este PC sera ESTACAO  (inicia com a sessao)
  [6] Remover inicializacao automatica
  --- Extras ---
  [7] Abrir SERVIDOR agora      [8] Abrir ESTACAO agora
  [9] Atualizar o programa (GitHub)
  [0] Sair
EOF
    read -r -p "Escolha: " op
    case "$op" in
        1) passo_deps; pausa ;;
        2) passo_motor; pausa ;;
        3) passo_sudoers; pausa ;;
        4) passo_autostart servidor; pausa ;;
        5) passo_autostart estacao; pausa ;;
        6) rm -f "$HOME/.config/autostart/justitoken-"{servidor,estacao}.desktop; echo "Removido."; pausa ;;
        7) (cd "$FONTES" && py usb_servidor.py &) ;;
        8) (cd "$FONTES" && py usb_estacao.py &) ;;
        9) (cd "$FONTES" && py atualizador.py --verificar; [ $? -eq 10 ] && { read -r -p "Aplicar agora? (s/N) " a; [ "$a" = s ] && py atualizador.py --aplicar; }); pausa ;;
        0) exit 0 ;;
    esac
done

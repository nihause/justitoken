# -*- coding: utf-8 -*-
"""
usbip_linux.py - Backend Linux do motor USB/IP.

No Linux nao existe usbipd-win nem usbip-win2: o proprio kernel traz o USB/IP
(modulos usbip-host no servidor e vhci-hcd na estacao) e o pacote "usbip"
traz as ferramentas. O protocolo e o mesmo, entao um servidor Linux atende uma
estacao Windows e vice-versa.

Este modulo expoe as MESMAS funcoes que o usbip_engine.py tem para o Windows;
o engine as troca por estas quando roda no Linux.
Tudo que exige root passa por scripts/justitoken-priv.sh (uma senha por acao).
"""

import os
import re
import sys
import glob
import shutil
import subprocess

PORTA_USBIP = 3240
HELPER_INSTALADO = "/usr/local/lib/justitoken/priv.sh"
_AQUI = os.path.dirname(os.path.abspath(__file__))


def _helper_local():
    base = getattr(sys, "_MEIPASS", _AQUI)
    return os.path.join(base, "scripts", "justitoken-priv.sh")


def _run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


def eh_admin():
    return os.geteuid() == 0


def _priv(*args, timeout=120):
    """Roda uma acao do ajudante privilegiado. Retorna (codigo, saida)."""
    args = [str(a) for a in args]
    if eh_admin():
        return _run(["sh", _helper_local(), *args], timeout=timeout)

    # 1) ajudante instalado (root) liberado no sudoers: sem senha
    if os.path.exists(HELPER_INSTALADO) and shutil.which("sudo"):
        cod, saida = _run(["sudo", "-n", HELPER_INSTALADO, *args], timeout=timeout)
        low = saida.lower()
        if not ("password" in low or "senha" in low or "sudoers" in low
                or "terminal" in low):
            return cod, saida.strip()

    # 2) pkexec: abre o dialogo grafico de senha do sistema
    pk = shutil.which("pkexec")
    if pk:
        alvo = HELPER_INSTALADO if os.path.exists(HELPER_INSTALADO) else _helper_local()
        return _run([pk, "/bin/sh", alvo, *args], timeout=timeout)

    return -1, ("Preciso de permissao de administrador e nao achei o pkexec. "
                "Instale o polkit (pkexec) ou rode o programa com sudo.")


# ---------------------------------------------------------------------------
# Ferramenta usbip
# ---------------------------------------------------------------------------
def caminho_usbip():
    achado = shutil.which("usbip")
    if achado:
        return achado
    for c in sorted(glob.glob("/usr/lib/linux-tools/*/usbip")
                    + glob.glob("/usr/lib/linux-tools-*/usbip")):
        if os.access(c, os.X_OK):
            return c
    return None


def _usbipd():
    return shutil.which("usbipd") or next(
        (c for c in glob.glob("/usr/lib/linux-tools/*/usbipd")
         + glob.glob("/usr/sbin/usbipd") if os.access(c, os.X_OK)), None)


# ===========================================================================
#  SERVIDOR
# ===========================================================================
def servidor_instalado():
    return caminho_usbip() is not None and _usbipd() is not None


def servidor_versao():
    exe = caminho_usbip()
    if not exe:
        return None
    cod, saida = _run([exe, "version"])
    return saida.strip().splitlines()[0] if cod == 0 and saida.strip() else "usbip (Linux)"


def instalar_servidor():
    cod, saida = _priv("instalar-pacotes", timeout=900)
    if servidor_instalado():
        return True, "Pacote usbip instalado."
    return False, f"Falha ao instalar o usbip (codigo {cod}). {saida.strip()[-300:]}"


def _ler(caminho):
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


def _clientes_conectados():
    """IPs com conexao aberta na porta usbip (para mostrar quem esta usando)."""
    cod, saida = _run(["ss", "-Htn", "state", "established", "sport", "=",
                       f":{PORTA_USBIP}"], timeout=5)
    if cod != 0:
        return None
    ips = []
    if cod == 0:
        for linha in saida.splitlines():
            partes = linha.split()
            if len(partes) >= 4:
                ip = partes[-1].rsplit(":", 1)[0].strip("[]")
                if ip.startswith("::ffff:"):
                    ip = ip[7:]
                ips.append(ip)
    return ips


def listar_dispositivos_servidor():
    """Mesmo formato do Windows: {busid, chave, vidpid, descricao, compartilhado, em_uso, cliente}."""
    exe = caminho_usbip()
    if not exe:
        return []
    cod, saida = _run([exe, "list", "-l"], timeout=20)
    if cod != 0:
        return []
    res = []
    atual = None
    for linha in saida.splitlines():
        m = re.match(r"^\s*-\s*busid\s+(\S+)\s+\(([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})\)", linha)
        if m:
            busid = m.group(1)
            sysfs = f"/sys/bus/usb/devices/{busid}"
            driver = os.path.basename(os.path.realpath(sysfs + "/driver")) \
                if os.path.exists(sysfs + "/driver") else ""
            compartilhado = driver == "usbip-host"
            status = _ler(f"/sys/bus/usb/drivers/usbip-host/{busid}/usbip_status")
            em_uso = compartilhado and status == "3"
            clientes = _clientes_conectados() if em_uso else []
            lista_clientes = clientes
            atual = {
                "busid": busid,
                "chave": (_ler(sysfs + "/serial") or busid).lower(),
                "vidpid": m.group(2).lower(),
                "descricao": "",
                "compartilhado": compartilhado,
                "em_uso": em_uso,
                "cliente": clientes[0] if clientes and len(clientes) == 1 else "",
                "clientes": lista_clientes,   # None = nao foi possivel descobrir
            }
            res.append(atual)
        elif atual is not None and not atual["descricao"] and linha.strip():
            desc = linha.strip()
            desc = re.sub(r"\s*\([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\)\s*$", "", desc)
            atual["descricao"] = desc or "Dispositivo USB"
    for d in res:
        d["descricao"] = d["descricao"] or "Dispositivo USB"
    return res


def compartilhar(busid):
    cod, saida = _priv("bind", busid)
    return cod == 0, saida.strip()


def descompartilhar(busid):
    cod, saida = _priv("unbind", busid)
    return cod == 0, saida.strip()


def forcar_liberar(busid):
    """Derruba o cliente atual: desfaz e refaz o bind desse busid. Retorna (ok, msg)."""
    import time
    antes = next((d for d in listar_dispositivos_servidor() if d["busid"] == busid), None)
    if antes is None:
        return False, f"{busid} nao encontrado no servidor"
    if not antes["compartilhado"]:
        return False, f"{busid} nao esta compartilhado no servidor"
    if not antes["em_uso"]:
        return True, ""
    cod, saida = _priv("rebind", busid, timeout=60)
    if cod != 0:
        return False, saida.strip() or "falha ao refazer o compartilhamento"
    fim = time.time() + 20
    while time.time() < fim:
        d = next((x for x in listar_dispositivos_servidor() if x["busid"] == busid), None)
        if d and d["compartilhado"] and not d["em_uso"]:
            time.sleep(1.5)
            return True, ""
        time.sleep(0.7)
    return False, "dispositivo ainda nao reapareceu livre no servidor"


def garantir_firewall_servidor():
    return _priv("firewall")[0] == 0


# ===========================================================================
#  ESTACAO / CLIENTE
# ===========================================================================
def caminho_cliente():
    return caminho_usbip()


def cliente_instalado():
    return caminho_usbip() is not None


def instalar_cliente(destino_dir=None, progresso=None):
    if progresso:
        progresso("Instalando o pacote usbip (confirme a senha de administrador)...")
    cod, saida = _priv("instalar-pacotes", timeout=900)
    if cliente_instalado():
        return True, "Pacote usbip instalado."
    return False, f"Falha ao instalar o usbip (codigo {cod}). {saida.strip()[-300:]}"


def anexar(servidor, busid):
    if not caminho_usbip():
        return False, "Cliente USB/IP nao instalado."
    cod, saida = _priv("attach", servidor, busid)
    return cod == 0, saida.strip()


def desanexar(porta):
    if not caminho_usbip():
        return False, "Cliente USB/IP nao instalado."
    cod, saida = _priv("detach", int(porta))
    return cod == 0, saida.strip()


# ===========================================================================
#  INICIAR COM O SISTEMA (autostart da area de trabalho, sem root)
# ===========================================================================
def _arq_autostart(nome):
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", f"{nome}.desktop")


def criar_tarefa_inicio(nome, exe_path):
    try:
        if exe_path.lower().endswith(".py"):
            comando = f'"{sys.executable}" "{exe_path}"'
        else:
            comando = f'"{exe_path}"'
        arq = _arq_autostart(nome)
        os.makedirs(os.path.dirname(arq), exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\n"
                    f"Name={nome}\nExec={comando}\n"
                    "X-GNOME-Autostart-enabled=true\nTerminal=false\n")
        return True
    except Exception:
        return False


def remover_tarefa_inicio(nome):
    try:
        os.remove(_arq_autostart(nome))
    except Exception:
        pass
    return True


def tarefa_existe(nome):
    return os.path.exists(_arq_autostart(nome))

# -*- coding: utf-8 -*-
"""
usbip_engine.py - Motor de redirecionamento USB/IP.

Orquestra as duas ferramentas que fazem o trabalho de kernel (que o Python
nao faz sozinho):

  SERVIDOR  -> usbipd-win  (dorssel)   : compartilha qualquer USB na rede.
  ESTACAO   -> usbip-win2  (vadimgrn)  : cliente (driver VHCI) que anexa o USB.

Aqui ficam: deteccao, instalacao, listagem, compartilhar/anexar.
Funciona com QUALQUER dispositivo USB: pendrive, HD, token, impressora, etc.
"""

import os
import re
import json
import time
import socket
import ctypes
import shutil
import tempfile
import threading
import subprocess
import urllib.request

IS_WIN = os.name == "nt"
SEM_JANELA = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW (so Windows)
PORTA_USBIP = 3240
PORTA_CONTROLE = 3241  # canal Estacao -> Servidor (pedir para liberar/forcar)

# Caminhos comuns onde o usbip.exe (cliente) costuma ficar instalado
CAMINHOS_CLIENTE = [
    r"C:\Program Files\USBip\usbip.exe",
    r"C:\Program Files (x86)\USBip\usbip.exe",
    r"C:\Program Files\usbip-win2\usbip.exe",
    r"C:\Program Files\usbip-win\usbip.exe",
    r"C:\Program Files (x86)\usbip-win2\usbip.exe",
]

# Pagina oficial de releases do cliente (driver VHCI)
URL_CLIENTE_RELEASES = "https://github.com/vadimgrn/usbip-win2/releases/latest"
API_CLIENTE_LATEST = "https://api.github.com/repos/vadimgrn/usbip-win2/releases/latest"
# Endereco usado caso a API do GitHub falhe (versao conhecida)
URL_CLIENTE_FALLBACK = ("https://github.com/vadimgrn/usbip-win2/releases/download/"
                        "v.0.9.7.7/USBip-0.9.7.7-x64.exe")
NOME_CLIENTE_FALLBACK = "USBip-0.9.7.7-x64.exe"


# ---------------------------------------------------------------------------
# Execucao de comandos
# ---------------------------------------------------------------------------
def _run(cmd, timeout=60):
    """Executa um comando (lista ou string) sem abrir janela. Retorna (cod, saida)."""
    try:
        p = subprocess.run(
            cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
            creationflags=SEM_JANELA, timeout=timeout, encoding="utf-8",
            errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


def eh_admin():
    """True se o processo atual ja esta elevado (admin)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_admin(exe, args, wait=True):
    """
    Roda um programa COMO ADMINISTRADOR, oculto.
    Se o processo atual JA for admin (ex.: iniciado por tarefa agendada),
    executa direto, SEM disparar UAC. Caso contrario, eleva via UAC.
    """
    if eh_admin():
        # Ja temos privilegio: roda direto, sem prompt.
        achado = shutil.which(exe) or exe
        return _run([achado] + list(args), timeout=120)

    arglist = ", ".join(f"'{a}'" for a in args)
    ps = (
        f"$p = Start-Process -FilePath '{exe}' "
        f"-ArgumentList @({arglist}) -Verb RunAs -WindowStyle Hidden "
        f"-PassThru -Wait; exit $p.ExitCode"
    )
    return _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps], timeout=120)


def _q(s):
    """Coloca aspas num argumento so se ele tiver espaco."""
    s = str(s)
    return f'"{s}"' if " " in s else s


def _run_admin_captura(exe, args, timeout=120):
    """
    Como _run_admin, mas CAPTURA a saida do programa MESMO quando elevado via UAC.

    O Windows nao deixa capturar o stdout de um processo aberto com
    'Start-Process -Verb RunAs'. Entao gravamos a saida do comando num arquivo
    (atraves de um .bat temporario) e lemos depois. Assim sempre conseguimos
    mostrar no log o motivo real de um erro (ex.: 'Device busy').
    Retorna (codigo, texto_da_saida).
    """
    achado = shutil.which(exe) or exe
    if eh_admin():
        # Ja somos admin: roda direto e captura normalmente.
        return _run([achado] + list(args), timeout=timeout)

    saida_txt = tempfile.mktemp(suffix=".usbout.txt")
    bat = tempfile.mktemp(suffix=".usbrun.bat")
    linha = '"' + achado + '" ' + " ".join(_q(a) for a in args)
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write("@echo off\r\n" + linha + ' > "' + saida_txt + '" 2>&1\r\n')
    except Exception as e:
        return -1, f"falha ao preparar o comando: {e}"

    ps = (f"$p = Start-Process -FilePath '{bat}' -Verb RunAs "
          f"-WindowStyle Hidden -PassThru -Wait; exit $p.ExitCode")
    cod, _ = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-Command", ps], timeout=timeout)

    texto = ""
    try:
        with open(saida_txt, encoding="utf-8", errors="replace") as fh:
            texto = fh.read().strip()
    except Exception:
        pass
    for caminho in (bat, saida_txt):
        try:
            os.remove(caminho)
        except Exception:
            pass
    return cod, texto


def _run_admin_visivel(exe, args=None, wait=True, timeout=900):
    """Como _run_admin, mas mostra a janela (para instaladores com assistente)."""
    if args:
        arglist = ", ".join(f"'{a}'" for a in args)
        arg_part = f"-ArgumentList @({arglist}) "
    else:
        arg_part = ""
    espera = "-Wait " if wait else ""
    ps = (f"$p = Start-Process -FilePath '{exe}' {arg_part}"
          f"-Verb RunAs {espera}-PassThru; "
          f"if($p -and $p.HasExited){{exit $p.ExitCode}}")
    return _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps], timeout=timeout)


# ===========================================================================
#  LADO SERVIDOR  (usbipd-win)
# ===========================================================================
def servidor_instalado():
    return shutil.which("usbipd") is not None


def servidor_versao():
    cod, saida = _run(["usbipd", "--version"])
    return saida.strip() if cod == 0 else None


def instalar_servidor():
    """Instala o usbipd-win via winget (como admin). Retorna (ok, msg)."""
    if not shutil.which("winget"):
        return False, "winget nao encontrado neste Windows."
    cod, saida = _run_admin(
        "winget",
        ["install", "--id", "dorssel.usbipd-win", "-e", "--silent",
         "--source", "winget",
         "--accept-package-agreements", "--accept-source-agreements"],
    )
    if servidor_instalado() or cod == 0:
        return True, "usbipd-win instalado. Pode ser necessario reabrir o programa."
    return False, f"Falha ao instalar (codigo {cod})."


def listar_dispositivos_servidor():
    """
    Lista os USB locais e o estado de cada um.
    Retorna lista de dicts: {busid, vidpid, descricao, compartilhado, em_uso, cliente}
    """
    # Tenta primeiro o formato JSON (usbipd state)
    cod, saida = _run(["usbipd", "state"])
    if cod == 0 and saida.strip().startswith("{"):
        try:
            dados = json.loads(saida)
            res = []
            for d in dados.get("Devices", []):
                instancia = d.get("InstanceId") or ""
                res.append({
                    "busid": d.get("BusId") or "",
                    "chave": instancia.rsplit("\\", 1)[-1].lower() or (d.get("BusId") or ""),
                    "vidpid": _vidpid_de_instance(d.get("InstanceId", "")),
                    "descricao": d.get("Description") or "Dispositivo USB",
                    "compartilhado": bool(d.get("PersistedGuid")),
                    "em_uso": bool(d.get("ClientIPAddress")),
                    "cliente": d.get("ClientIPAddress") or "",
                })
            # so itens com busid (os "persisted" sem busid sao ignorados)
            return [r for r in res if r["busid"]]
        except Exception:
            pass

    # Fallback: parse de "usbipd list"
    return _parse_usbipd_list()


def dispositivo_servidor(busid):
    """Retorna o dispositivo do servidor pelo busid, ou None se nao apareceu."""
    for disp in listar_dispositivos_servidor():
        if disp.get("busid") == busid:
            return disp
    return None


def _vidpid_de_instance(instance_id):
    m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", instance_id or "")
    return f"{m.group(1)}:{m.group(2)}".lower() if m else ""


def _parse_usbipd_list():
    cod, saida = _run(["usbipd", "list"])
    if cod != 0:
        return []
    res = []
    secao_conectados = False
    for linha in saida.splitlines():
        s = linha.strip()
        if s.lower().startswith("connected"):
            secao_conectados = True
            continue
        if s.lower().startswith("persisted"):
            secao_conectados = False
            continue
        if not secao_conectados or not s or s.upper().startswith("BUSID"):
            continue
        m = re.match(r"^(\d+-\d+(?:\.\d+)*)\s+([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4})\s+(.*?)\s{2,}(.+)$", s)
        if m:
            estado = m.group(4).strip().lower()
            res.append({
                "busid": m.group(1),
                "chave": m.group(1),
                "vidpid": m.group(2).lower(),
                "descricao": m.group(3).strip(),
                "compartilhado": "shared" in estado and "not shared" not in estado,
                "em_uso": "attached" in estado or "used" in estado,
                "cliente": "",
            })
    return res


def compartilhar(busid):
    """Compartilha um dispositivo (usbipd bind). Exige admin -> dispara UAC."""
    cod, saida = _run_admin_captura("usbipd", ["bind", "--force", f"--busid={busid}"])
    return cod == 0, saida.strip()


def descompartilhar(busid):
    cod, saida = _run_admin_captura("usbipd", ["unbind", f"--busid={busid}"])
    return cod == 0, saida.strip()


def _livre(disp):
    return bool(disp and disp.get("compartilhado") and not disp.get("em_uso"))


def _aguardar_livre_servidor(busid, timeout=15, estabilizar=2.0):
    """
    Aguarda o usbipd terminar o reset e mostrar o busid livre de cliente.
    Depois de livre, espera 'estabilizar' segundos e confere de novo: logo apos
    a desconexao o dispositivo (ex.: token) ainda esta reiniciando e um attach
    imediato falha.
    """
    fim = time.time() + timeout
    ultimo = None
    while time.time() < fim:
        ultimo = dispositivo_servidor(busid)
        if _livre(ultimo):
            time.sleep(estabilizar)
            ultimo = dispositivo_servidor(busid)
            if _livre(ultimo):
                return True, ""
            continue
        time.sleep(0.7)
    if ultimo and ultimo.get("em_uso"):
        cliente = ultimo.get("cliente") or "outro computador"
        return False, f"dispositivo ainda aparece em uso por {cliente}"
    return False, "dispositivo ainda nao reapareceu livre no servidor"


# Um "forcar" por busid de cada vez (varios cliques / estacoes ao mesmo tempo)
_travas_busid = {}
_travas_lock = threading.Lock()


def _trava(busid):
    with _travas_lock:
        return _travas_busid.setdefault(busid, threading.Lock())


def forcar_liberar(busid):
    """
    Forca a desconexao do cliente que esta usando o dispositivo, deixando o
    busid livre para outra estacao anexar. Roda no SERVIDOR. Exige admin.
    Mexe SOMENTE nesse busid (nunca derruba as outras estacoes).
    Retorna (ok, mensagem).
    """
    with _trava(busid):
        antes = dispositivo_servidor(busid)
        if antes is None:
            # pode estar reiniciando por causa de um forcar anterior
            return _aguardar_livre_servidor(busid, timeout=10)
        if not antes.get("compartilhado"):
            return False, f"{busid} nao esta compartilhado no servidor"
        if not antes.get("em_uso"):
            return True, ""

        saidas = []

        # 1) detach so desse busid: o cliente ve como se o USB fosse removido
        cod, saida = _run_admin_captura("usbipd", ["detach", f"--busid={busid}"],
                                        timeout=30)
        if saida:
            saidas.append(saida.strip())
        ok, msg = _aguardar_livre_servidor(busid)
        if ok:
            return True, ""
        saidas.append(msg)

        # 2) nao soltou: desfaz e refaz o compartilhamento desse busid,
        #    o que encerra a conexao do cliente a forca
        _, saida = _run_admin_captura("usbipd", ["unbind", f"--busid={busid}"],
                                      timeout=30)
        if saida:
            saidas.append(saida.strip())
        _, saida = _run_admin_captura("usbipd", ["bind", "--force", f"--busid={busid}"],
                                      timeout=30)
        if saida:
            saidas.append(saida.strip())
        ok, msg = _aguardar_livre_servidor(busid, timeout=25)
        if ok:
            return True, ""
        saidas.append(msg)
        return False, " | ".join(s for s in saidas if s) or "usbipd detach falhou"


def garantir_firewall_servidor():
    """Garante regras de firewall liberando as portas 3240 (usbip) e 3241 (controle)."""
    for porta, regra in ((PORTA_USBIP, "USBIP Servidor 3240"),
                         (PORTA_CONTROLE, "USBIP Controle 3241")):
        _run_admin("powershell", [
            "-NoProfile", "-Command",
            f"if(-not (Get-NetFirewallRule -DisplayName '{regra}' "
            f"-ErrorAction SilentlyContinue)){{New-NetFirewallRule "
            f"-DisplayName '{regra}' -Direction Inbound -Action Allow "
            f"-Protocol TCP -LocalPort {porta}}}",
        ])


# ===========================================================================
#  LADO ESTACAO / CLIENTE  (usbip-win2)
# ===========================================================================
def caminho_cliente():
    """Retorna o caminho do usbip.exe (cliente) ou None se nao instalado."""
    # 1) caminhos conhecidos
    for c in CAMINHOS_CLIENTE:
        if os.path.exists(c):
            return c
    # 2) no PATH
    achado = shutil.which("usbip")
    if achado:
        return achado
    # 3) busca em Program Files (qualquer subpasta) como ultimo recurso
    bases = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    for base in bases:
        if not base or not os.path.isdir(base):
            continue
        try:
            for nome in os.listdir(base):
                alvo = os.path.join(base, nome, "usbip.exe")
                if os.path.exists(alvo):
                    return alvo
        except Exception:
            pass
    return None


def cliente_instalado():
    return caminho_cliente() is not None


def _url_instalador_cliente():
    """Descobre o .exe da ultima versao via API do GitHub (com fallback)."""
    try:
        req = urllib.request.Request(API_CLIENTE_LATEST,
                                     headers={"User-Agent": "usb-estacao"})
        with urllib.request.urlopen(req, timeout=20) as r:
            dados = json.load(r)
        for a in dados.get("assets", []):
            nome = a.get("name", "")
            if nome.lower().endswith(".exe"):
                return a["browser_download_url"], nome
    except Exception:
        pass
    return URL_CLIENTE_FALLBACK, NOME_CLIENTE_FALLBACK


def baixar_instalador_cliente(destino_dir=None, progresso=None):
    """
    Baixa o instalador do cliente. 'progresso' recebe um texto de status.
    Retorna o caminho do arquivo baixado.
    """
    url, nome = _url_instalador_cliente()
    destino_dir = destino_dir or tempfile.gettempdir()
    destino = os.path.join(destino_dir, nome)

    if progresso:
        progresso(f"Baixando {nome} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "usb-estacao"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        baixado = 0
        with open(destino, "wb") as f:
            while True:
                bloco = r.read(262144)
                if not bloco:
                    break
                f.write(bloco)
                baixado += len(bloco)
                if progresso and total:
                    pct = baixado * 100 // total
                    progresso(f"Baixando {nome} ... {pct}%")
    return destino


def instalar_cliente(destino_dir=None, progresso=None):
    """
    Baixa e executa o instalador do cliente USB/IP (assistente visivel, admin).
    Retorna (ok, msg).
    """
    try:
        instalador = baixar_instalador_cliente(destino_dir, progresso)
    except Exception as e:
        return False, f"Falha ao baixar o instalador: {e}"

    if progresso:
        progresso("Abrindo o instalador (confirme o administrador)...")
    _run_admin_visivel(instalador, args=None, wait=True)

    if cliente_instalado():
        return True, "Cliente USB/IP instalado."
    return (False, "O instalador foi executado, mas o cliente nao foi detectado. "
                   "Se ele pediu reinicio, reinicie e reabra a estacao.")


def listar_dispositivos_remotos(servidor):
    """
    Lista os USB exportados por um servidor remoto.
    Retorna lista de dicts: {busid, descricao}
    """
    exe = caminho_cliente()
    if not exe:
        return []
    cod, saida = _run([exe, "list", "-r", servidor], timeout=30)
    res = []
    for linha in saida.splitlines():
        # formato tipico: "   1-4: Descricao do dispositivo : (vid:pid)"
        m = re.match(r"^\s*(\d+-\d+(?:\.\d+)*)\s*:\s*(.+)$", linha)
        if m:
            res.append({"busid": m.group(1),
                        "descricao": m.group(2).strip().rstrip(":").strip()})
    return res


def erro_dispositivo_ocupado(msg):
    low = (msg or "").lower()
    return any(t in low for t in (
        "busy",
        "exported",
        "in use",
        "used by",
        "ocupado",
        "em uso",
        "ja esta anexado",
        "já está anexado",
        "already attached",
    ))


def anexar(servidor, busid):
    """Anexa um dispositivo remoto neste PC (usbip attach). Exige admin -> UAC."""
    exe = caminho_cliente()
    if not exe:
        return False, "Cliente USB/IP nao instalado."
    cod, saida = _run_admin_captura(exe, ["attach", "-r", servidor, "-b", busid])
    return cod == 0, saida.strip()


def tomar_dispositivo(servidor, busid, progresso=None, forcar_antes=False,
                      tempo_max=30):
    """
    Garante o dispositivo NESTA estacao, derrubando quem estiver usando.

    - forcar_antes=False: tenta anexar; so derruba o outro se vier "ocupado".
    - forcar_antes=True : ja pede ao servidor para derrubar o uso atual.

    Depois de liberado, tenta anexar varias vezes por ate 'tempo_max' segundos
    (o USB reinicia apos a desconexao e os primeiros attach podem falhar).
    Se outro computador pegar de volta nesse meio tempo, derruba mais uma vez.
    Retorna (ok, msg, tomou_de_outro).
    """
    if not forcar_antes:
        ok, msg = anexar(servidor, busid)
        if ok or not erro_dispositivo_ocupado(msg):
            return ok, msg, False

    ultimo_msg = ""
    for rodada in range(2):
        if progresso:
            progresso("Pedindo ao servidor para derrubar o uso atual..." if rodada == 0
                      else "Outro computador pegou de novo; derrubando mais uma vez...")
        ok_forcar, msg_forcar = pedir_forcar(servidor, busid)
        if not ok_forcar:
            return False, msg_forcar, False

        if progresso:
            progresso("Liberado no servidor. Anexando aqui...")
        fim = time.time() + tempo_max
        espera = 1.5
        while True:
            ok, msg = anexar(servidor, busid)
            if ok:
                return True, msg, True
            ultimo_msg = msg
            if not msg and not eh_admin():
                return False, "permissao de administrador negada", True
            if erro_dispositivo_ocupado(msg):
                break  # alguem pegou de volta: nova rodada de forcar
            if time.time() + espera > fim:
                return False, msg or "falha ao anexar depois de liberar", True
            time.sleep(espera)
            espera = min(espera + 1.0, 4.0)

    return False, ultimo_msg or "falha ao anexar depois de liberar", True


def desanexar(porta):
    exe = caminho_cliente()
    if not exe:
        return False, "Cliente USB/IP nao instalado."
    cod, saida = _run_admin_captura(exe, ["detach", "-p", str(porta)])
    return cod == 0, saida.strip()


def consultar_servidor(servidor, timeout=8):
    """
    Pergunta ao SERVIDOR (porta 3241) a versao dele, o nome de cada dispositivo
    e quem esta usando cada um. Retorna dict ou None se nao respondeu:
      {"versao": "2.0.0" | None, "voce": "<ip desta estacao visto pelo servidor>",
       "dispositivos": {busid: {"nome", "descricao", "em_uso", "cliente"}}}
    Servidor de versao antiga (sem esse comando) volta com versao None.
    """
    try:
        with socket.create_connection((servidor, PORTA_CONTROLE), timeout=timeout) as s:
            s.sendall(b"INFO\n")
            partes = []
            while True:
                bloco = s.recv(65536)
                if not bloco:
                    break
                partes.append(bloco)
                if bloco.endswith(b"\n"):
                    break
        texto = b"".join(partes).decode("utf-8", "replace").strip()
    except Exception:
        return None
    if not texto.startswith("{"):
        return {"versao": None, "voce": "", "dispositivos": {}}
    try:
        dados = json.loads(texto)
    except Exception:
        return None
    dados["dispositivos"] = {d.get("busid"): d for d in dados.get("dispositivos", [])}
    return dados


def pedir_forcar(servidor, busid, timeout=150):
    """
    Pede ao SERVIDOR (canal de controle, porta 3241) que solte o dispositivo,
    desconectando o cliente que o estiver usando. Retorna (ok, mensagem).
    """
    try:
        with socket.create_connection((servidor, PORTA_CONTROLE), timeout=10) as s:
            s.settimeout(timeout)  # o servidor so responde depois de liberar
            s.sendall(f"FORCAR {busid}\n".encode("utf-8"))
            resp = s.recv(256).decode("utf-8", "replace").strip()
        if resp.upper().startswith("OK"):
            return True, ""
        return False, resp or "resposta vazia do servidor"
    except Exception as e:
        return False, (f"sem resposta do servidor em {servidor}:{PORTA_CONTROLE} "
                       f"({e}). Atualize o Servidor e libere o firewall.")


def listar_anexados():
    """
    Lista os dispositivos atualmente anexados nesta estacao (usbip port).
    Retorna lista de dicts: {porta, descricao, servidor, busid}
    """
    exe = caminho_cliente()
    if not exe:
        return []
    cod, saida = _run([exe, "port"], timeout=20)
    res = []
    porta_atual = None
    for linha in saida.splitlines():
        m = re.search(r"Port\s+(\d+)", linha)
        if m:
            porta_atual = m.group(1)
            res.append({"porta": porta_atual, "descricao": "",
                        "servidor": "", "busid": ""})
            continue

        if porta_atual and res:
            url = re.search(r"usbip://([^:/\s]+)(?::\d+)?/(\d+-\d+(?:\.\d+)*)", linha)
            if url:
                res[-1]["servidor"] = url.group(1)
                res[-1]["busid"] = url.group(2)
                continue

        if porta_atual and linha.strip() and res:
            texto = linha.strip()
            if texto.startswith("->"):
                continue
            if re.fullmatch(r"[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}", texto):
                continue
            if not res[-1]["descricao"]:
                res[-1]["descricao"] = texto
    return res


# ===========================================================================
#  INICIAR COM O WINDOWS (Tarefa Agendada, elevada, SEM UAC no boot)
# ===========================================================================
def criar_tarefa_inicio(nome, exe_path):
    """
    Cria uma Tarefa Agendada que abre o programa no logon, JA como admin
    (assim o auto-conectar funciona sem pedir UAC toda vez).
    """
    cod, _ = _run_admin("schtasks", [
        "/Create", "/TN", nome, "/TR", f'"{exe_path}"',
        "/SC", "ONLOGON", "/RL", "HIGHEST", "/F",
    ])
    return cod == 0


def remover_tarefa_inicio(nome):
    _run_admin("schtasks", ["/Delete", "/TN", nome, "/F"])
    return True


def tarefa_existe(nome):
    cod, _ = _run(["schtasks", "/Query", "/TN", nome])
    return cod == 0


# ===========================================================================
#  LINUX: troca as funcoes do Windows pelas do backend nativo (usbip do kernel)
# ===========================================================================
if not IS_WIN:
    from usbip_linux import (  # noqa: E402,F401
        eh_admin, servidor_instalado, servidor_versao, instalar_servidor,
        listar_dispositivos_servidor, compartilhar, descompartilhar,
        forcar_liberar, garantir_firewall_servidor, caminho_cliente,
        cliente_instalado, instalar_cliente, anexar, desanexar,
        criar_tarefa_inicio, remover_tarefa_inicio, tarefa_existe,
    )

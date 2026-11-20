# -*- coding: utf-8 -*-
"""
common.py - Funcoes e constantes compartilhadas entre o Servidor e a Estacao.

Faz parte do "Emulador de USB pela Rede".
Detecta pendrives, descobre IP local, le/grava configuracao e define o tema visual.
"""

import os
import sys
import string
import socket
import ctypes
import configparser

# ---------------------------------------------------------------------------
# Tema visual (usado pelo CustomTkinter)
# ---------------------------------------------------------------------------
APP_NAME = "Nihause Token"

# Controle de versao: aumente a cada nova compilacao distribuida.
# O Servidor informa a versao dele para as Estacoes, que avisam se for diferente.
VERSAO = "2.0.0"
DATA_VERSAO = "13/09/2026"

EMPRESA = "JustiSoft"
URL_DOWNLOADS = "https://justisoft.com.br/downloads/"
TEXTO_CREDITO = "Sistema desenvolvido pela JustiSoft  •  versão 100% gratuita"

COR_FUNDO      = "#0f1420"
COR_PAINEL     = "#1a2233"
COR_DESTAQUE   = "#3b82f6"   # azul
COR_DESTAQUE2  = "#2563eb"
COR_SUCESSO    = "#22c55e"   # verde
COR_ERRO       = "#ef4444"   # vermelho
COR_AVISO      = "#f59e0b"   # ambar
COR_TEXTO      = "#e5e7eb"
COR_TEXTO_FRACO = "#94a3b8"

IS_WIN        = sys.platform.startswith("win")
IS_LINUX      = sys.platform.startswith("linux")
# Segoe UI so existe no Windows; no Linux o Tk cai em uma fonte sans do sistema.
FONTE         = "Segoe UI" if IS_WIN else "DejaVu Sans"
FONTE_MONO    = "Consolas" if IS_WIN else "DejaVu Sans Mono"

if IS_WIN:
    MOTOR_SERVIDOR = "usbipd-win"
    MOTOR_CLIENTE = "usbip-win2"
    TXT_INICIAR_SISTEMA = "▶ Iniciar com o Windows (sem UAC)"
    TXT_CONFIG_INICIO = "Configurando inicio com o Windows (pede admin 1 vez)..."
    TXT_INSTALANDO_SERVIDOR = "Instalando usbipd-win via winget (vai pedir admin)..."
    TXT_REINICIO = " (pode pedir reinicio uma vez)."
else:
    MOTOR_SERVIDOR = "usbip (kernel Linux)"
    MOTOR_CLIENTE = "usbip (kernel Linux)"
    TXT_INICIAR_SISTEMA = "▶ Iniciar com a sessao do Linux"
    TXT_CONFIG_INICIO = "Configurando inicio automatico (autostart da area de trabalho)..."
    TXT_INSTALANDO_SERVIDOR = "Instalando o pacote usbip (vai pedir a senha de administrador)..."
    TXT_REINICIO = "."

PORTA_PADRAO  = 8472   # porta padrao do servidor WebDAV

# Pasta de configuracao: C:\usb
# - rodando como .py  -> um nivel acima de C:\usb\fontes
# - rodando como .exe -> a propria pasta do executavel (C:\usb)
if getattr(sys, "frozen", False):
    PASTA_BASE = os.path.dirname(sys.executable)
else:
    PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pasta_gravavel(pasta):
    try:
        teste = os.path.join(pasta, ".escrita_teste")
        with open(teste, "w") as f:
            f.write("x")
        os.remove(teste)
        return True
    except Exception:
        return False


# Instalado em lugar sem permissao de escrita (ex.: /opt, Program Files):
# guarda config, sessao e log na pasta do usuario.
if not _pasta_gravavel(PASTA_BASE):
    if IS_WIN:
        PASTA_BASE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "JustiToken")
    else:
        PASTA_BASE = os.path.join(os.environ.get("XDG_CONFIG_HOME")
                                  or os.path.expanduser("~/.config"), "justitoken")
    os.makedirs(PASTA_BASE, exist_ok=True)
CONFIG_PATH  = os.path.join(PASTA_BASE, "config.ini")


def aplicar_icone(janela, nome):
    """Icone da janela: .ico no Windows; no Linux (X11) usa a imagem via PIL."""
    arq = caminho_recurso("assets", "icones", nome + ".ico")
    if IS_WIN:
        janela.iconbitmap(arq)
        return
    from PIL import Image, ImageTk
    img = Image.open(arq).convert("RGBA").resize((64, 64))
    janela._icone_tk = ImageTk.PhotoImage(img)  # guarda referencia
    janela.iconphoto(True, janela._icone_tk)


def caminho_recurso(*partes):
    """Retorna um recurso tanto no fonte quanto dentro do executavel."""
    raiz = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, *partes)


# ---------------------------------------------------------------------------
# Deteccao de unidades removiveis (pendrives) no Windows
# ---------------------------------------------------------------------------
DRIVE_REMOVABLE = 2
DRIVE_FIXED     = 3


def _rotulo_volume(raiz):
    """Retorna o rotulo (nome) de um volume, ex: 'KINGSTON'."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        fsbuf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(raiz), buf, ctypes.sizeof(buf),
            None, None, None, fsbuf, ctypes.sizeof(fsbuf),
        )
        return buf.value or ""
    except Exception:
        return ""


def listar_unidades(incluir_fixas=False):
    """
    Lista as unidades disponiveis.
    Retorna lista de dicts: {raiz, letra, rotulo, tipo, removivel}
    Por padrao retorna apenas removiveis (pendrives / HDs externos).
    """
    resultado = []
    if not IS_WIN:
        return _listar_unidades_linux()
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return resultado

    for i, letra in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        raiz = f"{letra}:\\"
        try:
            tipo = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(raiz))
        except Exception:
            tipo = 0

        removivel = (tipo == DRIVE_REMOVABLE)
        if not removivel and not (incluir_fixas and tipo == DRIVE_FIXED):
            continue

        resultado.append({
            "raiz": raiz,
            "letra": letra,
            "rotulo": _rotulo_volume(raiz),
            "tipo": tipo,
            "removivel": removivel,
        })
    return resultado


def _listar_unidades_linux():
    """Pendrives/HDs montados em /media, /run/media ou /mnt (formato igual ao do Windows)."""
    res = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            linhas = f.read().splitlines()
    except Exception:
        return res
    for linha in linhas:
        partes = linha.split()
        if len(partes) < 3:
            continue
        ponto = partes[1].replace("\040", " ")
        if ponto.startswith(("/media/", "/run/media/", "/mnt/")):
            res.append({"raiz": ponto, "letra": os.path.basename(ponto),
                        "rotulo": os.path.basename(ponto), "tipo": DRIVE_REMOVABLE,
                        "removivel": True})
    return res


def letras_de_unidade_livres():
    """Retorna letras de unidade NAO utilizadas (para montar na estacao).
    No Linux nao ha letras de unidade: o compartilhamento vira uma pasta."""
    if not IS_WIN:
        return []
    usadas = set()
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letra in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                usadas.add(letra)
    except Exception:
        pass
    # Preferimos do fim do alfabeto pra frente (Z, Y, X ...)
    livres = [l for l in reversed(string.ascii_uppercase) if l not in usadas]
    return livres


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def ip_local():
    """Descobre o IP local 'de saida' da maquina (o que outros PCs usam)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def nome_maquina():
    try:
        return socket.gethostname()
    except Exception:
        return "PC"


# ---------------------------------------------------------------------------
# Configuracao persistente
# ---------------------------------------------------------------------------
SECAO = "config"


def _coerce(v):
    """Converte texto do ini para tipo (bool/int) quando faz sentido."""
    s = str(v).strip()
    low = s.lower()
    if low in ("true", "sim", "on", "yes"):
        return True
    if low in ("false", "nao", "não", "off", "no"):
        return False
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except Exception:
            pass
    return s


def carregar_config():
    """Le o config.ini e retorna um dict (com tipos inferidos)."""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        p = configparser.ConfigParser()
        try:
            p.read(CONFIG_PATH, encoding="utf-8")
            if p.has_section(SECAO):
                for k, v in p.items(SECAO):
                    cfg[k] = _coerce(v)
        except Exception:
            pass
    return cfg


def salvar_config(dados):
    """Grava/atualiza chaves no config.ini (secao [config])."""
    try:
        p = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            p.read(CONFIG_PATH, encoding="utf-8")
        if not p.has_section(SECAO):
            p.add_section(SECAO)
        for k, v in dados.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            p.set(SECAO, str(k), str(v))
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            p.write(f)
        return True
    except Exception:
        return False


def get_lista(cfg, chave):
    """Le uma chave que guarda varios valores separados por virgula."""
    bruto = str(cfg.get(chave, "") or "")
    return [x.strip() for x in bruto.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Nomes dos dispositivos (ex.: "Token Rodrigo"), secao [nomes] do config.ini
# A chave e o numero de serie do USB, entao o nome acompanha o token mesmo
# se ele for plugado em outra porta.
# ---------------------------------------------------------------------------
SECAO_NOMES = "nomes"


def _parser_nomes():
    p = configparser.ConfigParser(interpolation=None)
    if os.path.exists(CONFIG_PATH):
        try:
            p.read(CONFIG_PATH, encoding="utf-8")
        except Exception:
            pass
    return p


def carregar_nomes():
    """Retorna {chave_do_dispositivo: nome}."""
    p = _parser_nomes()
    if not p.has_section(SECAO_NOMES):
        return {}
    return {k.lower(): v for k, v in p.items(SECAO_NOMES) if v.strip()}


def salvar_nome(chave, nome):
    """Grava o nome de um dispositivo. Nome vazio remove."""
    try:
        p = _parser_nomes()
        if not p.has_section(SECAO_NOMES):
            p.add_section(SECAO_NOMES)
        chave = str(chave).lower()
        nome = (nome or "").strip()
        if nome:
            p.set(SECAO_NOMES, chave, nome)
        else:
            p.remove_option(SECAO_NOMES, chave)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            p.write(f)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rodape (barra de status + credito JustiSoft), igual no Servidor e na Estacao
# ---------------------------------------------------------------------------
def criar_rodape(janela, nome_app=None):
    """
    Monta o rodape no fundo da janela. Chame ANTES de empacotar o resto da
    interface, para ele nunca ser espremido. Retorna o label de status.
    """
    import webbrowser
    import customtkinter as ctk

    rodape = ctk.CTkFrame(janela, fg_color=COR_PAINEL, corner_radius=0)
    rodape.pack(fill="x", side="bottom")

    linha1 = ctk.CTkFrame(rodape, fg_color="transparent")
    linha1.pack(fill="x", padx=16, pady=(6, 0))
    ctk.CTkLabel(linha1, text=f"🔑 {nome_app or APP_NAME}  v{VERSAO}",
                 font=(FONTE, 12, "bold"),
                 text_color=COR_DESTAQUE).pack(side="left")
    lbl_status = ctk.CTkLabel(linha1, text="Iniciando...", anchor="w",
                              font=(FONTE, 12), text_color=COR_TEXTO_FRACO)
    lbl_status.pack(side="left", padx=(12, 0))

    linha2 = ctk.CTkFrame(rodape, fg_color="transparent")
    linha2.pack(fill="x", padx=16, pady=(0, 6))
    ctk.CTkLabel(linha2, text=TEXTO_CREDITO, font=(FONTE, 11),
                 text_color=COR_TEXTO_FRACO).pack(side="left")
    link = ctk.CTkLabel(linha2, text="⬇ Baixar em justisoft.com.br/downloads",
                        font=(FONTE, 11, "underline"),
                        text_color=COR_DESTAQUE, cursor="hand2")
    link.pack(side="right")
    link.bind("<Button-1>", lambda _e: webbrowser.open(URL_DOWNLOADS))
    return lbl_status


# ---------------------------------------------------------------------------
# Log persistente (compartilhado entre Servidor e Estacao)
# ---------------------------------------------------------------------------
import datetime as _datetime  # noqa: E402

LOG_PATH = os.path.join(PASTA_BASE, "usb-rede.log")


def registrar_log(origem, msg):
    """Acrescenta uma linha com data/hora ao arquivo de log (C:\\usb\\usb-rede.log)."""
    try:
        carimbo = _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{carimbo}  [{origem}]  {msg}\n")
    except Exception:
        pass


def tamanho_legivel(num):
    """Converte bytes para texto legivel (KB, MB, GB...)."""
    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unidade}"
        num /= 1024.0
    return f"{num:.1f} PB"

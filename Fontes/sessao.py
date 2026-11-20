# -*- coding: utf-8 -*-
"""
sessao.py - Sessao do usuario logado na ESTACAO + autorizacoes de uso do token.

- A senha NUNCA e gravada.
- O token de sessao so e gravado se o usuario marcar "Manter conectado".
  No Windows fica protegido pelo DPAPI (CryptProtectData): o arquivo so abre
  pelo mesmo usuario, neste mesmo computador. No Linux nao ha equivalente sem
  dependencias extras, entao grava SO o token (nunca a senha) em arquivo com
  permissao 0600 (somente o dono le).
- As autorizacoes vigentes (para a contagem de 1 hora e a reconexao automatica)
  ficam em autorizacoes.json, com o prazo calculado pela resposta da API.
"""

import os
import json
import time
import base64
import ctypes
import datetime
import threading

import common

ARQ_SESSAO = os.path.join(common.PASTA_BASE, "sessao.dat")
ARQ_AUTORIZACOES = os.path.join(common.PASTA_BASE, "autorizacoes.json")
_ENTROPIA = b"JustiToken-Estacao-v3"


# ---------------------------------------------------------------------------
# DPAPI (Windows)
# ---------------------------------------------------------------------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados):
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _DATA_BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(dados, proteger):
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    entrada, _b1 = _blob(dados)
    entropia, _b2 = _blob(_ENTROPIA)
    saida = _DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if proteger:
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), "JustiToken", ctypes.byref(entropia),
                                      None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                      ctypes.byref(saida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia),
                                        None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                        ctypes.byref(saida))
    if not ok:
        raise OSError("DPAPI falhou")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def dpapi_disponivel():
    return hasattr(ctypes, "windll")


def _ler_bruto():
    """Le o arquivo da sessao e devolve o dict, em qualquer sistema."""
    with open(ARQ_SESSAO, "rb") as f:
        conteudo = f.read()
    if dpapi_disponivel():
        return json.loads(_dpapi(base64.b64decode(conteudo), proteger=False).decode("utf-8"))
    return json.loads(conteudo.decode("utf-8"))


# ---------------------------------------------------------------------------
# Sessao
# ---------------------------------------------------------------------------
class Sessao:
    def __init__(self, token="", usuario=None, expira_em="", senha=""):
        self.token = token
        self.usuario = usuario or {}
        self.expira_em = expira_em or ""
        # Nunca e registrada em log; so e persistida quando o usuario escolhe
        # manter conectado, dentro do mesmo blob protegido pelo DPAPI.
        self.senha = senha or ""

    @property
    def nome(self):
        return self.usuario.get("nome") or self.usuario.get("login") or "usuario"

    def para_dict(self):
        return {"token": self.token, "usuario": self.usuario,
                "expira_em": self.expira_em, "senha": self.senha}


def salvar_sessao(sessao):
    """Grava a sessao protegida por DPAPI. Retorna True se gravou."""
    try:
        dados = sessao.para_dict()
        if not dpapi_disponivel():
            dados["senha"] = ""  # fora do Windows a senha nunca vai para o disco
            fd = os.open(ARQ_SESSAO, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(json.dumps(dados, ensure_ascii=False).encode("utf-8"))
            os.chmod(ARQ_SESSAO, 0o600)
            return True
        bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        cifrado = _dpapi(bruto, proteger=True)
        with open(ARQ_SESSAO, "wb") as f:
            f.write(base64.b64encode(cifrado))
        return True
    except Exception:
        return False


def carregar_sessao():
    """Le a sessao salva. Retorna Sessao ou None."""
    if not os.path.exists(ARQ_SESSAO):
        return None
    try:
        d = _ler_bruto()
        if not d.get("token"):
            return None
        return Sessao(d["token"], d.get("usuario") or {}, d.get("expira_em") or "",
                      d.get("senha") or "")
    except Exception:
        apagar_sessao()
        return None


def carregar_credenciais():
    """Devolve usuário/senha salvos em DPAPI, inclusive se o token expirou."""
    if not os.path.exists(ARQ_SESSAO):
        return {}
    try:
        d = _ler_bruto()
        return {"usuario": (d.get("usuario") or {}).get("login", ""),
                "senha": d.get("senha") or ""}
    except Exception:
        return {}


def limpar_token_salvo():
    """Remove token vencido mas preserva a senha DPAPI para novo login manual."""
    cred = carregar_credenciais()
    if not cred.get("senha"):  # sem senha guardada (ex.: Linux): so apaga
        apagar_sessao()
        return
    salvar_sessao(Sessao("", {"login": cred["usuario"]}, "", cred["senha"]))


def apagar_sessao():
    try:
        if os.path.exists(ARQ_SESSAO):
            os.remove(ARQ_SESSAO)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Autorizacoes de uso (contagem regressiva)
# ---------------------------------------------------------------------------
_lock = threading.Lock()


class Autorizacao:
    """Uma autorizacao de uso de um dispositivo (servidor + busid).

    O prazo e guardado como 'deadline_epoch' (relogio desta maquina), calculado
    UMA vez a partir dos segundos informados pela API. A contagem usa tambem o
    relogio monotonico, entao mudar a hora do Windows nao estica o prazo.
    """

    def __init__(self, servidor, busid, usuario_id, usuario_login, segundos,
                 autorizacao_id=None, nome="", descricao="", expira_em_api="",
                 concedida_epoch=None, deadline_epoch=None):
        self.servidor = servidor
        self.busid = busid
        self.usuario_id = usuario_id
        self.usuario_login = usuario_login
        self.autorizacao_id = autorizacao_id
        self.nome = nome
        self.descricao = descricao
        self.expira_em_api = expira_em_api
        agora = time.time()
        self.concedida_epoch = concedida_epoch or agora
        self.deadline_epoch = deadline_epoch or (agora + max(0, int(segundos)))
        self._deadline_mono = time.monotonic() + (self.deadline_epoch - agora)
        self.avisada = False
        self.encerrada = False

    @property
    def chave(self):
        return (self.servidor, self.busid)

    def segundos_restantes(self):
        # o menor dos dois: relogio monotonico (nao muda) e relogio de parede
        rest_mono = self._deadline_mono - time.monotonic()
        rest_wall = self.deadline_epoch - time.time()
        return max(0, int(min(rest_mono, rest_wall)))

    def expirada(self):
        return self.segundos_restantes() <= 0

    def hora_expiracao(self):
        return datetime.datetime.fromtimestamp(self.deadline_epoch).strftime("%H:%M")

    def ajustar(self, segundos):
        """A API informou um prazo menor (nunca aumenta: sem renovacao automatica)."""
        if segundos is None:
            return
        novo = time.time() + max(0, int(segundos))
        if novo < self.deadline_epoch:
            self.deadline_epoch = novo
            self._deadline_mono = time.monotonic() + max(0, int(segundos))

    def dispositivo(self):
        return {"servidor": self.servidor, "busid": self.busid,
                "nome": self.nome, "descricao": self.descricao}

    def para_dict(self):
        return {"servidor": self.servidor, "busid": self.busid,
                "usuario_id": self.usuario_id, "usuario_login": self.usuario_login,
                "autorizacao_id": self.autorizacao_id, "nome": self.nome,
                "descricao": self.descricao, "expira_em_api": self.expira_em_api,
                "concedida_epoch": self.concedida_epoch,
                "deadline_epoch": self.deadline_epoch}

    @classmethod
    def de_dict(cls, d):
        return cls(d.get("servidor", ""), d.get("busid", ""), d.get("usuario_id"),
                   d.get("usuario_login", ""), 0, d.get("autorizacao_id"),
                   d.get("nome", ""), d.get("descricao", ""), d.get("expira_em_api", ""),
                   d.get("concedida_epoch"), d.get("deadline_epoch"))


def formatar_tempo(segundos):
    segundos = max(0, int(segundos))
    h, r = divmod(segundos, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def salvar_autorizacoes(lista):
    with _lock:
        try:
            with open(ARQ_AUTORIZACOES, "w", encoding="utf-8") as f:
                json.dump([a.para_dict() for a in lista if not a.encerrada], f,
                          ensure_ascii=False, indent=1)
        except Exception:
            pass


def carregar_autorizacoes(usuario, incluir_vencidas=False):
    """Carrega as autorizacoes deste usuario. Com incluir_vencidas=True traz
    tambem as que venceram com o programa fechado (para desanexar e registrar)."""
    with _lock:
        try:
            with open(ARQ_AUTORIZACOES, encoding="utf-8") as f:
                brutos = json.load(f)
        except Exception:
            return []
    res = []
    for d in brutos if isinstance(brutos, list) else []:
        mesmo = ((d.get("usuario_id") is not None and d.get("usuario_id") == usuario.get("id"))
                 or (d.get("usuario_id") is None
                     and d.get("usuario_login") == usuario.get("login")))
        if not mesmo:
            continue
        a = Autorizacao.de_dict(d)
        if incluir_vencidas or not a.expirada():
            res.append(a)
    return res

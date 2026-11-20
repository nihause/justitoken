# -*- coding: utf-8 -*-
"""
api_client.py - Comunicacao da ESTACAO com a API JustiSoft (HTTPS + JSON).

Usado somente pela Estacao (usb_estacao.py). Nao altera nada do Servidor,
do motor USB/IP nem das portas 3240/3241.

Endpoints (base configuravel pela chave 'api_base' do config.ini) — conferidos
na API real "API JustiSoft — Autenticação e Logs de Assinatura USB" v2.1.0:
  POST {base}/login                 -> autentica usuario/senha (Bearer token)
  GET  {base}/validate              -> valida sessao e licenca; 401 se a sessao
                                       for invalida OU o usuario estiver desativado
  POST {base}/logout                -> encerra a sessao e revoga o token
  POST {base}/eventos/assinatura    -> registra eventos; a resposta da
                                       SOLICITACAO_TOKEN_USB traz a autorizacao
  GET  {base}/token/autorizacao/<id> -> (opcional) estado de uma autorizacao

Todas as funcoes aqui sao BLOQUEANTES: chame-as sempre dentro de uma thread
(nunca na thread do CustomTkinter).
"""

import os
import ssl
import json
import uuid
import socket
import getpass
import datetime
import threading
import urllib.request
import urllib.error

import common

API_BASE_PADRAO = "https://rodrigonchagas.adv.br/api/user"
TIMEOUT = 15
ARQ_PENDENTES = os.path.join(common.PASTA_BASE, "eventos_pendentes.jsonl")
MAX_PENDENTES = 2000

# Nomes dos eventos de auditoria
EV_LOGIN = "LOGIN_REALIZADO"
EV_LOGOUT = "LOGOUT"
EV_SOLICITACAO = "SOLICITACAO_TOKEN_USB"
EV_ANEXADO = "TOKEN_ANEXADO"
EV_FALHA_ANEXO = "FALHA_ANEXACAO"
EV_DESANEXADO = "TOKEN_DESANEXADO"
EV_EXPIRACAO = "EXPIRACAO_AUTORIZACAO"
EV_PERDA = "PERDA_UTILIZACAO"
EV_RECONEXAO = "RECONEXAO_AUTOMATICA"

_lock_pendentes = threading.Lock()
_cfg_api = {}
_lock_cfg = threading.Lock()


class ErroApi(Exception):
    """Erro de comunicacao/resposta da API.

    status = codigo HTTP (0 quando nem chegou na API: rede, DNS, SSL...).
    """

    def __init__(self, mensagem, status=0, dados=None):
        super().__init__(mensagem)
        self.status = status
        self.dados = dados or {}

    @property
    def sem_conexao(self):
        return self.status == 0

    @property
    def nao_autorizado(self):
        return self.status in (401, 419)


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def _cfg():
    """Le 'api_base'/'api_permitir_http' UMA vez (o config.ini e regravado por
    outras rotinas e uma leitura no meio da gravacao viria vazia)."""
    with _lock_cfg:
        if not _cfg_api:
            cfg = common.carregar_config()
            _cfg_api["base"] = (str(cfg.get("api_base", "") or "").strip()
                                or API_BASE_PADRAO).rstrip("/")
            _cfg_api["http"] = str(cfg.get("api_permitir_http", "")).lower() == "true"
        return _cfg_api


def api_base():
    return _cfg()["base"]


def agora_iso():
    """Data/hora local com fuso, ex.: 2026-10-16T08:30:00-03:00."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def nome_computador():
    return os.environ.get("COMPUTERNAME") or common.nome_maquina()


def usuario_windows():
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _mensagem_de(dados, padrao=""):
    if isinstance(dados, dict):
        for k in ("erro", "mensagem", "message", "error", "detail", "msg"):
            v = dados.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return padrao


def requisicao(metodo, caminho, dados=None, token=None, timeout=TIMEOUT):
    """Faz a chamada HTTP e devolve o JSON (dict). Levanta ErroApi."""
    url = api_base() + caminho
    if not url.lower().startswith("https://") and not _cfg()["http"]:
        raise ErroApi("A API precisa usar HTTPS.", 0)

    corpo = None
    cab = {
        "Accept": "application/json",
        "User-Agent": f"JustiToken-Estacao/{common.VERSAO}",
    }
    if dados is not None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        cab["Content-Type"] = "application/json; charset=utf-8"
    if token:
        cab["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=corpo, headers=cab, method=metodo)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            bruto = r.read().decode("utf-8", "replace").strip()
            status = r.status
    except urllib.error.HTTPError as e:
        try:
            bruto = e.read().decode("utf-8", "replace").strip()
            info = json.loads(bruto) if bruto.startswith(("{", "[")) else {}
        except Exception:
            info = {}
        msg = _mensagem_de(info, f"A API respondeu HTTP {e.code}.")
        raise ErroApi(msg, e.code, info if isinstance(info, dict) else {})
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErroApi(f"Sem conexao com a API ({motivo}).", 0)

    if not bruto:
        return {}
    try:
        info = json.loads(bruto)
    except Exception:
        raise ErroApi("Resposta invalida da API (nao e JSON).", status)
    if not isinstance(info, dict):
        info = {"dados": info}
    # Algumas APIs respondem 200 com {"ok": false} / {"success": false}
    for chave in ("ok", "success", "sucesso"):
        if info.get(chave) is False:
            raise ErroApi(_mensagem_de(info, "A API recusou a operacao."), 400, info)
    return info


# ---------------------------------------------------------------------------
# Usuario / sessao
# ---------------------------------------------------------------------------
_VALORES_ATIVO = {"1", "true", "s", "sim", "ativo", "active", "a", "y", "yes"}


def _extrair_usuario(info):
    """Aceita {usuario:{...}}, {user:{...}}, {data/dados:{...}} ou o proprio dict."""
    for k in ("usuario", "user", "data", "dados"):
        v = info.get(k)
        if isinstance(v, dict):
            if isinstance(v.get("user"), dict):
                return v["user"]
            if isinstance(v.get("usuario"), dict):
                return v["usuario"]
            return v
    return info


def usuario_ativo(usuario):
    """True/False se a API informou o status; None se nao informou."""
    for k in ("ativo", "active", "status", "situacao"):
        if k in usuario:
            v = usuario.get(k)
            if isinstance(v, bool):
                return v
            if v is None:
                return False
            return str(v).strip().lower() in _VALORES_ATIVO
    return None


def _normalizar_usuario(u):
    nome = (u.get("nome") or u.get("name") or u.get("login")
            or u.get("usuario") or u.get("username") or "")
    return {
        "id": u.get("id") or u.get("usuario_id") or u.get("user_id"),
        "nome": str(nome),
        "login": str(u.get("login") or u.get("usuario") or u.get("username")
                     or u.get("email") or nome),
        "ativo": usuario_ativo(u),
    }


def login(usuario, senha):
    """
    Autentica. Retorna dict {token, expira_em, usuario:{id,nome,login,ativo}}.
    Levanta ErroApi (credenciais invalidas, usuario inativo, sem conexao...).
    """
    info = requisicao("POST", "/login", {
        "usuario": usuario,
        "senha": senha,
        "computador": nome_computador(),
        "app": "JustiToken-Estacao",
        "versao_app": common.VERSAO,
    })
    token = None
    for fonte in (info, info.get("data") if isinstance(info.get("data"), dict) else {},
                  info.get("dados") if isinstance(info.get("dados"), dict) else {}):
        token = (fonte.get("access_token") or fonte.get("token")
                 or fonte.get("api_token"))
        if token:
            break
    if not token:
        raise ErroApi("A API nao devolveu o token de sessao.", 200, info)

    u = _normalizar_usuario(_extrair_usuario(info))
    if u["ativo"] is not False:
        # confirma no /validate (a API responde 401 para usuario desativado)
        u2 = obter_usuario(token)
        u = {**u, **{k: v for k, v in u2.items() if v not in (None, "")}}
    if not u["ativo"]:
        raise ErroApi("Usuario inativo. Procure o administrador.", 403, info)
    if not u["nome"]:
        u["nome"] = usuario
    if not u["login"]:
        u["login"] = usuario
    return {"token": token,
            "expira_em": info.get("expira_em") or info.get("expires_at") or "",
            "usuario": u}


def obter_usuario(token):
    """GET {base}/validate -> usuario normalizado.
    Sessao aceita pelo /validate = sessao valida e usuario ATIVO (a API responde
    401 "Sessão inválida, expirada ou usuário desativado" caso contrario).
    Se a resposta trouxer explicitamente ativo/status, esse valor prevalece."""
    info = requisicao("GET", "/validate", token=token)
    u = _normalizar_usuario(_extrair_usuario(info))
    for k in ("valido", "valid", "ativo"):
        if info.get(k) is False:
            u["ativo"] = False
    if u["ativo"] is None:
        u["ativo"] = True
    return u


def logout(token):
    try:
        requisicao("POST", "/logout", {"computador": nome_computador()},
                   token=token, timeout=8)
    except ErroApi:
        pass


# ---------------------------------------------------------------------------
# Eventos de auditoria
# ---------------------------------------------------------------------------
def montar_evento(evento, status, sessao=None, dispositivo=None, detalhe="",
                  autorizacao_id=None, extra=None):
    """Monta o JSON padrao dos eventos. A identidade oficial e a da sessao (Bearer);
    'usuario_login' vai so como informacao."""
    d = dispositivo or {}
    ev = {
        "id_evento": str(uuid.uuid4()),
        "evento": evento,
        "computador": nome_computador(),
        "data_hora_cliente": agora_iso(),
        "status": status,
        "usuario_login": (sessao.usuario.get("login") if sessao and sessao.usuario else ""),
        "usuario_windows": usuario_windows(),
        "dispositivo": {
            "servidor": d.get("servidor", ""),
            "busid": d.get("busid", ""),
            "nome": d.get("nome", ""),
            "descricao": d.get("descricao", ""),
        },
        "autorizacao_id": autorizacao_id,
        "detalhe": detalhe or "",
        "app": "JustiToken-Estacao",
        "versao_app": common.VERSAO,
    }
    if extra:
        ev.update(extra)
    return ev


def enviar_evento(sessao, evento_json, enfileirar=True):
    """
    Envia um evento. Se nao houver conexao, guarda em eventos_pendentes.jsonl
    para reenviar depois (somente quando 'enfileirar'). Retorna a resposta (dict)
    ou None se ficou pendente. Levanta ErroApi para 401 (sessao invalida).
    """
    token = sessao.token if sessao else None
    try:
        return requisicao("POST", "/eventos/assinatura", evento_json, token=token)
    except ErroApi as e:
        if e.nao_autorizado:
            if enfileirar:
                _guardar_pendente(sessao, evento_json)  # reenvia apos novo login
            raise
        if enfileirar and (e.sem_conexao or e.status >= 500):
            _guardar_pendente(sessao, evento_json)
            return None
        common.registrar_log("ESTACAO", f"[API] evento {evento_json.get('evento')} "
                                        f"recusado: {e}")
        return None


def _guardar_pendente(sessao, ev):
    reg = {"usuario_id": sessao.usuario.get("id") if sessao and sessao.usuario else None,
           "usuario_login": ev.get("usuario_login", ""),
           "evento": ev}
    with _lock_pendentes:
        try:
            linhas = []
            if os.path.exists(ARQ_PENDENTES):
                with open(ARQ_PENDENTES, encoding="utf-8") as f:
                    linhas = [l for l in f.read().splitlines() if l.strip()]
            linhas.append(json.dumps(reg, ensure_ascii=False))
            linhas = linhas[-MAX_PENDENTES:]
            with open(ARQ_PENDENTES, "w", encoding="utf-8") as f:
                f.write("\n".join(linhas) + "\n")
        except Exception:
            pass


def reenviar_pendentes(sessao):
    """Reenvia eventos guardados offline do MESMO usuario. Retorna quantos enviou."""
    if not sessao or not sessao.token:
        return 0
    with _lock_pendentes:
        if not os.path.exists(ARQ_PENDENTES):
            return 0
        try:
            with open(ARQ_PENDENTES, encoding="utf-8") as f:
                regs = [json.loads(l) for l in f.read().splitlines() if l.strip()]
        except Exception:
            return 0
        meu = sessao.usuario.get("id")
        meu_login = sessao.usuario.get("login")
        restantes, enviados = [], 0
        sem_rede = False
        for r in regs:
            mesmo = (r.get("usuario_id") == meu and meu is not None) or \
                    (r.get("usuario_id") is None and r.get("usuario_login") == meu_login)
            if sem_rede or not mesmo:
                restantes.append(r)
                continue
            ev = dict(r.get("evento") or {})
            ev["reenviado"] = True
            try:
                requisicao("POST", "/eventos/assinatura", ev, token=sessao.token)
                enviados += 1
            except ErroApi as e:
                if e.sem_conexao or e.status >= 500 or e.nao_autorizado:
                    sem_rede = True
                    restantes.append(r)
                # 4xx (exceto 401): a API recusou o evento; descarta para nao travar a fila
        try:
            if restantes:
                with open(ARQ_PENDENTES, "w", encoding="utf-8") as f:
                    f.write("\n".join(json.dumps(x, ensure_ascii=False)
                                      for x in restantes) + "\n")
            else:
                os.remove(ARQ_PENDENTES)
        except Exception:
            pass
        return enviados


# ---------------------------------------------------------------------------
# Autorizacao de uso do token (prazo definido pela API)
# ---------------------------------------------------------------------------
def _parse_data(txt):
    if not txt:
        return None
    s = str(txt).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def segundos_restantes_da_resposta(info, padrao=3600):
    """
    Calcula quantos segundos restam a partir da resposta da API, SEM depender do
    relogio desta estacao: usa 'segundos_restantes' ou (expira_em - agora_servidor).
    Retorna (segundos, origem) — origem: 'api', 'relogio_local' ou 'padrao'.
    """
    for k in ("segundos_restantes", "expira_em_segundos", "expires_in"):
        if info.get(k) is not None:
            try:
                return max(0, int(float(info[k]))), "api"
            except Exception:
                pass
    exp = _parse_data(info.get("expira_em") or info.get("expires_at"))
    agora_srv = _parse_data(info.get("agora_servidor") or info.get("data_hora_servidor")
                            or info.get("server_time") or info.get("servidor_utc")
                            or info.get("timestamp"))
    if exp is not None and agora_srv is not None:
        if (exp.tzinfo is None) != (agora_srv.tzinfo is None):
            # um com fuso e outro sem: o sem fuso e tratado como horario local
            exp = exp.astimezone() if exp.tzinfo is None else exp
            agora_srv = agora_srv.astimezone() if agora_srv.tzinfo is None else agora_srv
        return max(0, int((exp - agora_srv).total_seconds())), "api"
    if exp is not None:
        agora = datetime.datetime.now().astimezone()
        if exp.tzinfo is None:
            agora = agora.replace(tzinfo=None)
        return max(0, int((exp - agora).total_seconds())), "relogio_local"
    return padrao, "padrao"


def autorizacao_da_resposta(info):
    """
    Interpreta a resposta da SOLICITACAO_TOKEN_USB.
    Retorna (autorizado: bool, dados: dict, mensagem: str).
    dados = {autorizacao_id, segundos, origem, expira_em_api}
    """
    bloco = info.get("autorizacao") if isinstance(info.get("autorizacao"), dict) else info
    autorizado = bloco.get("autorizado", info.get("autorizado"))
    if autorizado is None:
        autorizado = True  # 2xx sem recusa explicita = concedido
    if isinstance(autorizado, str):
        autorizado = autorizado.strip().lower() in _VALORES_ATIVO
    msg = _mensagem_de(info, "")
    if not autorizado:
        return False, {}, msg or "A API nao autorizou o uso do token."
    segundos, origem = segundos_restantes_da_resposta(bloco)
    if not bloco.get("autorizacao_id"):
        return False, {}, "A API nao devolveu o identificador da autorizacao."
    if segundos <= 0:
        return False, {}, "A autorizacao recebida da API ja expirou."
    return True, {
        "autorizacao_id": bloco.get("autorizacao_id"),
        "segundos": segundos,
        "origem": origem,
        "expira_em_api": bloco.get("expira_em") or bloco.get("expires_at") or "",
    }, msg


def solicitar_token(sessao, dispositivo, acao):
    """
    Registra a SOLICITACAO_TOKEN_USB e devolve a autorizacao concedida pela API.
    NAO entra na fila offline: sem API, a solicitacao e negada (falha fechada).
    Retorna (autorizado, dados, mensagem). Levanta ErroApi em falha de rede/401.
    """
    ev = montar_evento(EV_SOLICITACAO, "SOLICITADO", sessao, dispositivo,
                       extra={"acao": acao})
    info = requisicao("POST", "/eventos/assinatura", ev, token=sessao.token)
    return autorizacao_da_resposta(info)


def consultar_autorizacao(sessao, autorizacao_id):
    """
    (Opcional) Consulta o estado de uma autorizacao na API.
    Retorna dict {ativa: bool|None, segundos: int|None, motivo: str} ou None
    quando a API nao oferece essa consulta (404/405) ou nao ha id.
    Levanta ErroApi para falta de conexao/401.
    """
    if not autorizacao_id:
        return None
    try:
        info = requisicao("GET", f"/token/autorizacao/{autorizacao_id}",
                          token=sessao.token, timeout=10)
    except ErroApi as e:
        if e.status in (404, 405, 501):
            return None
        raise
    bloco = info.get("autorizacao") if isinstance(info.get("autorizacao"), dict) else info
    ativa = bloco.get("ativa", bloco.get("valida"))
    if ativa is None and bloco.get("estado"):
        ativa = str(bloco["estado"]).upper() in ("ATIVA", "CONCEDIDA")
    seg = None
    if any(bloco.get(k) for k in ("segundos_restantes", "expira_em", "expires_at")):
        seg, _ = segundos_restantes_da_resposta(bloco)
    return {"ativa": ativa, "segundos": seg,
            "motivo": str(bloco.get("estado") or bloco.get("motivo") or "")}

# -*- coding: utf-8 -*-
"""
atualizador.py - Atualizacao automatica do JustiToken a partir do GitHub.

Como funciona
-------------
- A versao do pacote fica no arquivo VERSION (raiz do projeto).
- Verificar: le o VERSION da branch principal no GitHub e compara com o local.
- Aplicar:
    * se a pasta e um clone git  -> "git pull --ff-only" (recusa se houver
      alteracao local, para nunca perder trabalho);
    * senao baixa o .zip da branch e troca so os arquivos do programa
      (codigo, assets, scripts, instaladores). config.ini, sessao, log e
      autorizacoes NUNCA sao tocados. Tudo que for substituido vai antes para
      .backup_atualizacao/<data-hora>/.
- Executavel empacotado (PyInstaller): nao se auto-substitui; abre a pagina de
  releases para baixar o novo.

Uso na linha de comando:
    python atualizador.py --verificar
    python atualizador.py --aplicar
"""

import os
import re
import sys
import json
import shutil
import tempfile
import zipfile
import datetime
import subprocess
import threading
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import common  # noqa: E402

# Repositorio publico (dono/nome). Pode ser trocado no config.ini: repo_github = dono/nome
REPO_PADRAO = "nihause/justitoken"
BRANCH_PADRAO = "main"

PASTA_APP = os.path.dirname(AQUI)  # raiz do projeto (pai de Fontes)
ARQ_VERSION = os.path.join(PASTA_APP, "VERSION")
PASTA_BACKUP = os.path.join(PASTA_APP, ".backup_atualizacao")

# O que uma atualizacao pode substituir (caminhos relativos a raiz do projeto).
# Nada fora desta lista e tocado: config.ini, sessao.dat, usb-rede.log, etc.
PERMITIDOS = (
    "VERSION", "README.md", "LICENSE", "LEIA-ME.txt",
    "instalar.bat", "instalar.sh", "atualizar.bat", "atualizar.sh",
    "usb-estacao.bat", "usb-estacao.vbs", "usb-servidor.bat", "usb-servidor.vbs",
    "usb-estacao.sh", "usb-servidor.sh", "config.example.ini",
    "Fontes/",
)
# Dentro de Fontes/ nunca sobrescreve estes (dados locais / lixo de build)
IGNORADOS = ("__pycache__", ".claude", "build", "dist", "backup_")
# Dados locais de cada PC: nunca sao substituidos, em qualquer pasta
LOCAIS = ("config.ini", "sessao.dat", "autorizacoes.json")


def _cfg():
    c = common.carregar_config()
    repo = str(c.get("repo_github") or REPO_PADRAO).strip()
    branch = str(c.get("branch_github") or BRANCH_PADRAO).strip()
    return repo, branch


def _frozen():
    return bool(getattr(sys, "frozen", False))


def _http(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"JustiToken-Atualizador/{versao_local()}"})
    return urllib.request.urlopen(req, timeout=timeout)


def _tupla(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def versao_local():
    try:
        with open(ARQ_VERSION, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def versao_remota(timeout=15):
    """Devolve a versao publicada no GitHub, ou None se nao deu para saber."""
    repo, branch = _cfg()
    try:
        with _http(f"https://raw.githubusercontent.com/{repo}/{branch}/VERSION", timeout) as r:
            txt = r.read(64).decode("utf-8", "replace").strip()
        return txt if re.fullmatch(r"\d+(\.\d+){1,3}", txt) else None
    except Exception:
        return None


def ha_atualizacao():
    """(disponivel, versao_local, versao_remota). Remota None = sem internet."""
    local = versao_local()
    remota = versao_remota()
    return (remota is not None and _tupla(remota) > _tupla(local)), local, remota


def _eh_clone_git():
    return os.path.isdir(os.path.join(PASTA_APP, ".git")) and shutil.which("git") is not None


def _git(*args):
    p = subprocess.run(["git", "-C", PASTA_APP, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _aplicar_git(progresso):
    _, branch = _cfg()
    cod, saida = _git("status", "--porcelain", "--untracked-files=no")
    if cod == 0 and saida:
        return False, ("Ha alteracoes locais nos arquivos do programa; para nao perde-las "
                       "a atualizacao foi cancelada. Faca commit/stash e tente de novo.")
    progresso("Baixando atualizacao (git pull)...")
    cod, saida = _git("pull", "--ff-only", "origin", branch)
    if cod != 0:
        return False, f"git pull falhou: {saida[-300:]}"
    return True, "Atualizado via git."


def _caminho_permitido(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/"):
        return False
    partes = rel.split("/")
    if partes[-1].lower() in LOCAIS or partes[-1].lower().endswith(".log"):
        return False
    if rel.startswith("Fontes/") and any(
            p == ign or p.startswith(ign) for p in partes[1:] for ign in IGNORADOS):
        return False
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in PERMITIDOS)


def _aplicar_zip(progresso):
    repo, branch = _cfg()
    url = f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
    tmp = tempfile.mkdtemp(prefix="justitoken_upd_")
    try:
        zpath = os.path.join(tmp, "pacote.zip")
        progresso("Baixando atualizacao...")
        with _http(url, timeout=60) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        if not zipfile.is_zipfile(zpath):
            return False, "O arquivo baixado nao e um zip valido."

        extr = os.path.join(tmp, "x")
        with zipfile.ZipFile(zpath) as z:
            nomes = z.namelist()
            raiz = nomes[0].split("/")[0] + "/"
            for n in nomes:  # proteção contra zip malicioso (path traversal)
                alvo = os.path.realpath(os.path.join(extr, n))
                if not alvo.startswith(os.path.realpath(extr) + os.sep):
                    return False, "Zip com caminho invalido, atualizacao cancelada."
            z.extractall(extr)
        origem = os.path.join(extr, raiz.rstrip("/"))
        if not os.path.isfile(os.path.join(origem, "VERSION")):
            return False, "O pacote baixado nao parece ser do JustiToken (sem VERSION)."

        backup = os.path.join(PASTA_BACKUP,
                              datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        trocados = 0
        progresso("Aplicando arquivos...")
        for base, _dirs, arquivos in os.walk(origem):
            for nome in arquivos:
                full = os.path.join(base, nome)
                rel = os.path.relpath(full, origem).replace("\\", "/")
                if not _caminho_permitido(rel):
                    continue
                destino = os.path.join(PASTA_APP, *rel.split("/"))
                if os.path.exists(destino):
                    with open(full, "rb") as a, open(destino, "rb") as b:
                        if a.read() == b.read():
                            continue
                    os.makedirs(os.path.dirname(os.path.join(backup, *rel.split("/"))),
                                exist_ok=True)
                    shutil.copy2(destino, os.path.join(backup, *rel.split("/")))
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                shutil.copy2(full, destino)
                trocados += 1
        return True, f"{trocados} arquivo(s) atualizado(s). Copia dos antigos em {backup}"
    except Exception as e:
        return False, f"Falha na atualizacao: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def aplicar(progresso=None):
    """Aplica a atualizacao. Retorna (ok, mensagem)."""
    progresso = progresso or (lambda _t: None)
    if _frozen():
        import webbrowser
        repo, _ = _cfg()
        webbrowser.open(f"https://github.com/{repo}/releases/latest")
        return False, ("Este e o executavel empacotado: baixe a nova versao na pagina de "
                       "releases que foi aberta no navegador.")
    if _eh_clone_git():
        return _aplicar_git(progresso)
    return _aplicar_zip(progresso)


def reiniciar():
    """Reabre o programa com os arquivos novos."""
    try:
        if os.name == "nt":
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Integracao com as janelas (Servidor / Estacao)
# ---------------------------------------------------------------------------
def verificar_em_segundo_plano(app, log):
    """Checa sem travar a janela; se houver versao nova, pergunta se atualiza.
    Desligue com  verificar_atualizacao = false  no config.ini."""
    if common.carregar_config().get("verificar_atualizacao") is False:
        return

    def _t():
        disponivel, local, remota = ha_atualizacao()
        if not disponivel:
            return
        app.after(0, lambda: _perguntar(app, log, local, remota))

    threading.Thread(target=_t, daemon=True).start()


def _perguntar(app, log, local, remota):
    from tkinter import messagebox
    log(f"Atualizacao disponivel: {local} -> {remota}.", "aviso")
    if _frozen():
        msg = (f"Ha uma versao nova ({remota}). Voce usa a {local}.\n\n"
               "Abrir a pagina de download?")
    else:
        msg = (f"Ha uma versao nova ({remota}). Voce usa a {local}.\n\n"
               "Atualizar agora? O programa reinicia sozinho.")
    if not messagebox.askyesno(common.APP_NAME, msg):
        return

    def _t():
        ok, texto = aplicar(lambda t: app.after(0, lambda: log(t, "info")))
        app.after(0, lambda: _fim(app, log, ok, texto))
    threading.Thread(target=_t, daemon=True).start()


def _fim(app, log, ok, texto):
    from tkinter import messagebox
    log(texto, "ok" if ok else "erro")
    if ok and not _frozen():
        messagebox.showinfo(common.APP_NAME, texto + "\n\nO programa vai reiniciar.")
        reiniciar()
    elif not ok:
        messagebox.showwarning(common.APP_NAME, texto)


if __name__ == "__main__":
    modo = (sys.argv[1] if len(sys.argv) > 1 else "--verificar")
    if modo == "--verificar":
        disp, loc, rem = ha_atualizacao()
        if rem is None:
            print(f"Versao local {loc}. Nao consegui consultar o GitHub (sem internet ou repositorio inexistente).")
            sys.exit(2)
        print(f"Versao local {loc}, publicada {rem}. " + ("HA ATUALIZACAO." if disp else "Voce esta em dia."))
        sys.exit(10 if disp else 0)
    elif modo == "--aplicar":
        ok, msg = aplicar(print)
        print(msg)
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(64)

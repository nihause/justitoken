# -*- coding: utf-8 -*-
"""
usb_estacao.py - ESTACAO do Emulador de USB pela Rede.

Roda no computador que vai USAR o pendrive remoto.
Conecta no Servidor (WebDAV) e monta o conteudo como uma LETRA DE UNIDADE
(ex: Z:), aparecendo no "Este Computador" como um drive normal.

Visual moderno com CustomTkinter.
"""

import os
import sys
import subprocess
import threading
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

try:
    import customtkinter as ctk
    from tkinter import messagebox
except Exception as e:  # pragma: no cover
    print("CustomTkinter nao instalado. Rode o instalar (instalar.bat ou instalar.sh).", e)
    sys.exit(1)


SEM_JANELA = 0x08000000 if common.IS_WIN else 0  # CREATE_NO_WINDOW


def _run(cmd):
    """Executa um comando sem abrir janela de console. Retorna (codigo, saida)."""
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                           text=True, creationflags=SEM_JANELA, timeout=30)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, str(e)


# ---------------------------------------------------------------------------
# Nucleo: montar / desmontar a unidade WebDAV
# ---------------------------------------------------------------------------
class GerenciadorMontagem:
    def __init__(self, log_callback=None):
        self.log = log_callback or (lambda msg, nivel="info": None)
        self.letra_montada = None

    # ---- Linux: GVFS (gio) monta o WebDAV sem root ----------------------
    def _montar_linux(self, servidor, porta):
        url = f"dav://{servidor}:{porta}/"
        self.log(f"Conectando {url} (gio mount) ...", "info")
        cod, saida = _run(["gio", "mount", url])
        if cod == 0 or "already mounted" in (saida or "").lower():
            self.letra_montada = url
            return True, f"Pasta {url} conectada (aparece no gerenciador de arquivos)."
        return False, ("Falha ao conectar. Instale o gvfs (gvfs-backends) e o gio.\n"
                       + (saida or "").strip())

    def garantir_webclient(self):
        """O redirecionador WebDAV do Windows depende do servico WebClient."""
        cod, saida = _run('sc query WebClient')
        if "RUNNING" in saida.upper():
            return True
        self.log("Iniciando servico WebClient do Windows...", "info")
        _run('sc config WebClient start= auto')
        cod, saida = _run('net start WebClient')
        cod2, saida2 = _run('sc query WebClient')
        if "RUNNING" in saida2.upper():
            return True
        self.log("Nao foi possivel iniciar o WebClient (talvez precise de "
                 "administrador).", "aviso")
        return False

    def montar(self, servidor, porta, letra):
        if self.letra_montada:
            self.desmontar()
        if not common.IS_WIN:
            return self._montar_linux(servidor, porta)

        self.garantir_webclient()

        url = f"http://{servidor}:{porta}/"
        destino = f"{letra}:"

        # Remove qualquer mapeamento antigo nessa letra
        _run(f'net use {destino} /delete /y')

        self.log(f"Conectando {url} em {destino} ...", "info")
        cod, saida = _run(f'net use {destino} "{url}" /persistent:yes')

        if cod == 0:
            self.letra_montada = letra
            return True, f"Unidade {letra}: conectada."

        # Tentativa alternativa via UNC (\\servidor@porta\)
        unc = rf'\\{servidor}@{porta}\\'
        cod2, saida2 = _run(f'net use {destino} "{unc}" /persistent:yes')
        if cod2 == 0:
            self.letra_montada = letra
            return True, f"Unidade {letra}: conectada."

        msg = (saida or "") + " | " + (saida2 or "")
        return False, f"Falha ao conectar.\n{msg.strip()}"

    def desmontar(self):
        if not self.letra_montada:
            return True, "Nada montado."
        if not common.IS_WIN:
            _run(["gio", "mount", "-u", self.letra_montada])
            self.letra_montada = None
            return True, "Desconectado."
        destino = f"{self.letra_montada}:"
        _run(f'net use {destino} /delete /y')
        letra = self.letra_montada
        self.letra_montada = None
        return True, f"Unidade {letra}: desconectada."


# ---------------------------------------------------------------------------
# Interface grafica
# ---------------------------------------------------------------------------
class AppEstacao(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{common.APP_NAME}  -  ESTACAO")
        self.geometry("680x620")
        self.minsize(620, 560)
        self.configure(fg_color=common.COR_FUNDO)

        self.gerente = GerenciadorMontagem(log_callback=self.adicionar_log)
        self._montar_ui()

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def _montar_ui(self):
        cfg = common.carregar_config()

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(22, 10))
        ctk.CTkLabel(topo, text="💾  Estacao de USB",
                     font=(common.FONTE, 26, "bold"),
                     text_color=common.COR_TEXTO).pack(anchor="w")
        ctk.CTkLabel(topo,
                     text="Acesse aqui o pendrive plugado no computador servidor.",
                     font=(common.FONTE, 13),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", pady=(2, 0))

        painel = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=16)
        painel.pack(fill="x", padx=24, pady=10)

        # Servidor
        ctk.CTkLabel(painel, text="Endereco do Servidor (IP ou nome)",
                     font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(
            anchor="w", padx=20, pady=(20, 2))
        self.entry_servidor = ctk.CTkEntry(painel, height=40,
                                           placeholder_text="ex: 192.168.0.10",
                                           font=(common.FONTE, 14))
        self.entry_servidor.insert(0, cfg.get("ultimo_servidor", ""))
        self.entry_servidor.pack(fill="x", padx=20, pady=(0, 10))

        # Porta + Letra
        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=20, pady=(0, 10))

        col1 = ctk.CTkFrame(linha, fg_color="transparent")
        col1.pack(side="left")
        ctk.CTkLabel(col1, text="Porta", font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w")
        self.entry_porta = ctk.CTkEntry(col1, width=120, height=40,
                                        font=(common.FONTE, 14))
        self.entry_porta.insert(0, str(cfg.get("porta", common.PORTA_PADRAO)))
        self.entry_porta.pack(pady=(2, 0))

        col2 = ctk.CTkFrame(linha, fg_color="transparent")
        col2.pack(side="left", padx=(30, 0))
        ctk.CTkLabel(col2, text="Letra da unidade",
                     font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w")
        livres = common.letras_de_unidade_livres()
        preferida = cfg.get("ultima_letra", "Z")
        if preferida not in livres and livres:
            preferida = livres[0]
        self.combo_letra = ctk.CTkOptionMenu(
            col2, values=livres or ["Z"], width=120, height=40,
            font=(common.FONTE, 14),
            fg_color=common.COR_FUNDO, button_color=common.COR_DESTAQUE2,
            button_hover_color=common.COR_DESTAQUE)
        self.combo_letra.set(preferida)
        self.combo_letra.pack(pady=(2, 0))

        self.btn_acao = ctk.CTkButton(
            painel, text="🔌  CONECTAR UNIDADE",
            font=(common.FONTE, 16, "bold"), height=52, corner_radius=12,
            fg_color=common.COR_DESTAQUE, hover_color=common.COR_DESTAQUE2,
            command=self.alternar_conexao)
        self.btn_acao.pack(fill="x", padx=20, pady=(14, 20))

        # Status
        self.painel_info = ctk.CTkFrame(self, fg_color=common.COR_PAINEL,
                                        corner_radius=16)
        self.painel_info.pack(fill="x", padx=24, pady=10)
        self.lbl_status = ctk.CTkLabel(self.painel_info, text="●  Desconectado",
                                       font=(common.FONTE, 15, "bold"),
                                       text_color=common.COR_ERRO)
        self.lbl_status.pack(anchor="w", padx=20, pady=(16, 4))

        self.btn_abrir = ctk.CTkButton(
            self.painel_info, text="📂  Abrir unidade no Explorer",
            font=(common.FONTE, 13), height=38,
            fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
            command=self.abrir_explorer, state="disabled")
        self.btn_abrir.pack(anchor="w", padx=20, pady=(0, 16))

        ctk.CTkLabel(self, text="Registro de atividade",
                     font=(common.FONTE, 12, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=26)
        self.caixa_log = ctk.CTkTextbox(self, height=130, font=(common.FONTE_MONO, 12),
                                        fg_color="#0b0f18",
                                        text_color=common.COR_TEXTO_FRACO,
                                        corner_radius=12)
        self.caixa_log.pack(fill="both", expand=True, padx=24, pady=(4, 22))
        self.caixa_log.configure(state="disabled")

    # ---- acoes ------------------------------------------------------------
    def alternar_conexao(self):
        if self.gerente.letra_montada:
            self.desconectar()
        else:
            self.conectar()

    def conectar(self):
        servidor = self.entry_servidor.get().strip()
        porta = self.entry_porta.get().strip()
        letra = self.combo_letra.get().strip()
        if not servidor:
            messagebox.showwarning(common.APP_NAME, "Informe o endereco do servidor.")
            return
        if not porta.isdigit():
            messagebox.showwarning(common.APP_NAME, "Porta invalida.")
            return

        self.btn_acao.configure(text="Conectando...", state="disabled")
        self.adicionar_log(f"Tentando conectar em {servidor}:{porta} ...", "info")

        def _trabalho():
            ok, msg = self.gerente.montar(servidor, porta, letra)
            self.after(0, lambda: self._fim_conexao(ok, msg, servidor, porta, letra))

        threading.Thread(target=_trabalho, daemon=True).start()

    def _fim_conexao(self, ok, msg, servidor, porta, letra):
        self.btn_acao.configure(state="normal")
        if ok:
            common.salvar_config({
                "ultimo_servidor": servidor,
                "porta": int(porta),
                "ultima_letra": letra,
            })
            self.adicionar_log(msg, "ok")
            self.lbl_status.configure(text=f"●  Conectado em {letra}:",
                                      text_color=common.COR_SUCESSO)
            self.btn_acao.configure(text="⏏  DESCONECTAR UNIDADE",
                                    fg_color=common.COR_ERRO, hover_color="#dc2626")
            self.btn_abrir.configure(state="normal")
        else:
            self.adicionar_log(msg, "erro")
            messagebox.showerror(common.APP_NAME, msg)
            self.btn_acao.configure(text="🔌  CONECTAR UNIDADE")

    def desconectar(self):
        ok, msg = self.gerente.desmontar()
        self.adicionar_log(msg, "aviso")
        self.lbl_status.configure(text="●  Desconectado", text_color=common.COR_ERRO)
        self.btn_acao.configure(text="🔌  CONECTAR UNIDADE",
                                fg_color=common.COR_DESTAQUE,
                                hover_color=common.COR_DESTAQUE2)
        self.btn_abrir.configure(state="disabled")

    def abrir_explorer(self):
        if self.gerente.letra_montada:
            if common.IS_WIN:
                _run(f'explorer {self.gerente.letra_montada}:\\')
            else:
                _run(["xdg-open", self.gerente.letra_montada])

    def adicionar_log(self, msg, nivel="info"):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        prefixo = {"ok": "[OK] ", "erro": "[ERRO] ",
                   "aviso": "[!] ", "info": ""}.get(nivel, "")
        self.caixa_log.configure(state="normal")
        self.caixa_log.insert("end", f"{hora}  {prefixo}{msg}\n")
        self.caixa_log.see("end")
        self.caixa_log.configure(state="disabled")

    def _ao_fechar(self):
        # Mantemos a unidade montada de proposito (persistent) ao fechar a janela.
        self.destroy()


if __name__ == "__main__":
    AppEstacao().mainloop()

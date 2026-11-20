# -*- coding: utf-8 -*-
"""
tela_login.py - Tela de login da ESTACAO (CustomTkinter).

E um CTkFrame desenhado DENTRO da janela principal (nao abre outra janela raiz),
no mesmo visual escuro do sistema. A chamada a API roda em thread.
"""

import threading

import customtkinter as ctk

import common
import api_client as api
import sessao as ss


class TelaLogin(ctk.CTkFrame):
    def __init__(self, master, ao_entrar, mensagem_inicial=""):
        """ao_entrar(sessao, manter_conectado, senha) e chamado na interface."""
        super().__init__(master, fg_color=common.COR_FUNDO)
        self.ao_entrar = ao_entrar
        self._ocupado = False

        caixa = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=16)
        caixa.place(relx=0.5, rely=0.45, anchor="center")

        ctk.CTkLabel(caixa, text=f"🔑  {common.APP_NAME}  •  Estação",
                     font=(common.FONTE, 24, "bold"),
                     text_color=common.COR_TEXTO).pack(padx=40, pady=(28, 2))
        ctk.CTkLabel(caixa, text="Entre com seu usuário JustiSoft para usar os tokens.",
                     font=(common.FONTE, 13),
                     text_color=common.COR_TEXTO_FRACO).pack(padx=40, pady=(0, 18))

        cfg = common.carregar_config()
        ctk.CTkLabel(caixa, text="Usuário", font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=40)
        self.entry_usuario = ctk.CTkEntry(caixa, width=340, height=40,
                                          font=(common.FONTE, 14))
        self.entry_usuario.pack(padx=40, pady=(2, 10))
        ultimo = str(cfg.get("ultimo_usuario", "") or "")
        if ultimo:
            self.entry_usuario.insert(0, ultimo)

        ctk.CTkLabel(caixa, text="Senha", font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=40)
        self.entry_senha = ctk.CTkEntry(caixa, width=340, height=40, show="•",
                                        font=(common.FONTE, 14))
        self.entry_senha.pack(padx=40, pady=(2, 10))

        # A senha, quando solicitada pelo usuario, fica no sessao.dat protegido
        # por DPAPI e so pode ser lida neste Windows por este usuario.
        cred = ss.carregar_credenciais()
        if cred.get("usuario") == ultimo and cred.get("senha"):
            self.entry_senha.insert(0, cred["senha"])

        self.var_manter = ctk.BooleanVar(value=bool(cfg.get("manter_conectado", False)))
        chk = ctk.CTkCheckBox(caixa, text="Manter conectado e salvar senha neste computador",
                              variable=self.var_manter, font=(common.FONTE, 12),
                              text_color=common.COR_TEXTO_FRACO)
        chk.pack(anchor="w", padx=40, pady=(0, 12))
        if not ss.dpapi_disponivel():
            chk.configure(state="disabled")

        self.btn_entrar = ctk.CTkButton(caixa, text="Entrar", width=340, height=44,
                                        font=(common.FONTE, 15, "bold"),
                                        fg_color=common.COR_DESTAQUE,
                                        hover_color=common.COR_DESTAQUE2,
                                        command=self.entrar)
        self.btn_entrar.pack(padx=40, pady=(0, 10))

        self.lbl_msg = ctk.CTkLabel(caixa, text=mensagem_inicial, wraplength=340,
                                    font=(common.FONTE, 12), justify="center",
                                    text_color=common.COR_AVISO)
        self.lbl_msg.pack(padx=40, pady=(0, 22))

        for w in (self.entry_usuario, self.entry_senha):
            w.bind("<Return>", lambda _e: self.entrar())
        self.after(150, self._focar)

    def _focar(self):
        try:
            (self.entry_senha if self.entry_usuario.get().strip()
             else self.entry_usuario).focus_set()
        except Exception:
            pass

    def mensagem(self, texto, cor=None):
        self.lbl_msg.configure(text=texto, text_color=cor or common.COR_AVISO)

    def ocupado(self, sim, texto="Entrando..."):
        self._ocupado = sim
        estado = "disabled" if sim else "normal"
        self.btn_entrar.configure(state=estado, text=texto if sim else "Entrar")
        self.entry_usuario.configure(state=estado)
        self.entry_senha.configure(state=estado)

    def entrar(self):
        if self._ocupado:
            return
        usuario = self.entry_usuario.get().strip()
        senha = self.entry_senha.get()
        if not usuario or not senha:
            self.mensagem("Informe usuário e senha.")
            return
        self.ocupado(True)
        self.mensagem("Validando na API JustiSoft...", common.COR_TEXTO_FRACO)
        manter = bool(self.var_manter.get())

        def _t():
            try:
                r = api.login(usuario, senha)
                s = ss.Sessao(r["token"], r["usuario"], r.get("expira_em", ""),
                              senha if manter else "")
                self.after(0, lambda: self._sucesso(s, usuario, manter, senha))
            except api.ErroApi as e:
                msg = str(e)
                if e.status in (401, 403, 422) and "inativo" not in msg.lower():
                    msg = msg or "Usuário ou senha inválidos."
                self.after(0, lambda: self._falha(msg, usuario))
            except Exception as e:  # pragma: no cover
                msg_erro = f"Erro inesperado: {e}"
                self.after(0, lambda: self._falha(msg_erro, usuario))
        threading.Thread(target=_t, daemon=True).start()

    def _sucesso(self, s, usuario, manter, senha):
        try:
            self.entry_senha.delete(0, "end")
        except Exception:
            pass
        common.salvar_config({"ultimo_usuario": usuario, "manter_conectado": manter})
        self.ao_entrar(s, manter, senha)

    def _falha(self, msg, usuario):
        self.ocupado(False)
        self.mensagem(msg, common.COR_ERRO)
        common.registrar_log("ESTACAO", f"[LOGIN] falha para '{usuario}': {msg}")
        try:
            self.entry_senha.delete(0, "end")
            self.entry_senha.focus_set()
        except Exception:
            pass

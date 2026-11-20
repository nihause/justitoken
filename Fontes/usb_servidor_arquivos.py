# -*- coding: utf-8 -*-
"""
usb_servidor.py - SERVIDOR do Emulador de USB pela Rede.

Roda no computador onde o pendrive esta plugado.
Compartilha o conteudo da unidade removivel via protocolo WebDAV (HTTP),
para que a "Estacao" monte como uma letra de unidade em outro computador,
dentro ou fora da rede.

Visual moderno com CustomTkinter.
"""

import os
import sys
import threading
import datetime

# Garante que conseguimos importar common.py mesmo iniciado de outra pasta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

try:
    import customtkinter as ctk
    from tkinter import messagebox
except Exception as e:  # pragma: no cover
    print("CustomTkinter nao instalado. Rode o instalar (instalar.bat ou instalar.sh).", e)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Nucleo: servidor WebDAV em thread
# ---------------------------------------------------------------------------
class ServidorWebDAV:
    def __init__(self, log_callback=None):
        self.thread = None
        self.servidor = None
        self.rodando = False
        self.log = log_callback or (lambda msg, nivel="info": None)

    def iniciar(self, caminho, porta, permitir_escrita=True):
        if self.rodando:
            return False, "Servidor ja esta rodando."

        try:
            from wsgidav.wsgidav_app import WsgiDAVApp
            from cheroot import wsgi
        except Exception:
            return False, ("Bibliotecas WebDAV nao instaladas.\n"
                           "Execute o instalar (instalar.bat ou instalar.sh).")

        if not os.path.exists(caminho):
            return False, "A unidade selecionada nao esta disponivel."

        config = {
            "host": "0.0.0.0",
            "port": int(porta),
            "provider_mapping": {"/": caminho},
            "simple_dc": {"user_mapping": {"*": True}},  # acesso anonimo
            "verbose": 1,
            "logging": {"enable_loggers": []},
            "property_manager": True,
            "lock_storage": True,
            "dir_browser": {"enable": True},
        }
        # Somente leitura?
        if not permitir_escrita:
            config["provider_mapping"] = {
                "/": {"root": caminho, "readonly": True}
            }

        try:
            app = WsgiDAVApp(config)
            self.servidor = wsgi.Server(("0.0.0.0", int(porta)), app)
            self.servidor.prepare()
        except Exception as e:
            return False, f"Nao foi possivel iniciar na porta {porta}:\n{e}"

        def _rodar():
            self.rodando = True
            try:
                self.servidor.serve()
            except Exception as e:
                self.log(f"Servidor parou: {e}", "erro")
            finally:
                self.rodando = False

        self.thread = threading.Thread(target=_rodar, daemon=True)
        self.thread.start()
        return True, "Servidor iniciado."

    def parar(self):
        if self.servidor:
            try:
                self.servidor.stop()
            except Exception:
                pass
        self.rodando = False
        self.servidor = None


# ---------------------------------------------------------------------------
# Interface grafica
# ---------------------------------------------------------------------------
class AppServidor(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{common.APP_NAME}  -  SERVIDOR")
        self.geometry("680x620")
        self.minsize(620, 560)
        self.configure(fg_color=common.COR_FUNDO)

        self.servidor = ServidorWebDAV(log_callback=self.adicionar_log)
        self.unidades = []

        self._montar_ui()
        self.atualizar_unidades()

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    # ---- construcao da UI -------------------------------------------------
    def _montar_ui(self):
        # Cabecalho
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(22, 10))

        ctk.CTkLabel(
            topo, text="🖥️  Servidor de USB",
            font=(common.FONTE, 26, "bold"),
            text_color=common.COR_TEXTO,
        ).pack(anchor="w")
        ctk.CTkLabel(
            topo, text="Compartilhe um pendrive deste PC com outros computadores.",
            font=(common.FONTE, 13), text_color=common.COR_TEXTO_FRACO,
        ).pack(anchor="w", pady=(2, 0))

        # Painel de configuracao
        painel = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=16)
        painel.pack(fill="x", padx=24, pady=10)

        # --- escolha da unidade
        linha1 = ctk.CTkFrame(painel, fg_color="transparent")
        linha1.pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(linha1, text="Pendrive / Unidade",
                     font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w")

        sel = ctk.CTkFrame(painel, fg_color="transparent")
        sel.pack(fill="x", padx=20, pady=(0, 8))
        self.combo_unidade = ctk.CTkOptionMenu(
            sel, values=["Nenhum pendrive detectado"],
            font=(common.FONTE, 14), dropdown_font=(common.FONTE, 13),
            fg_color=common.COR_FUNDO, button_color=common.COR_DESTAQUE2,
            button_hover_color=common.COR_DESTAQUE, width=420, height=40,
        )
        self.combo_unidade.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            sel, text="↻ Atualizar", width=120, height=40,
            font=(common.FONTE, 13),
            fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
            command=self.atualizar_unidades,
        ).pack(side="left", padx=(10, 0))

        # --- porta e permissoes
        linha2 = ctk.CTkFrame(painel, fg_color="transparent")
        linha2.pack(fill="x", padx=20, pady=(8, 8))

        col_porta = ctk.CTkFrame(linha2, fg_color="transparent")
        col_porta.pack(side="left")
        ctk.CTkLabel(col_porta, text="Porta",
                     font=(common.FONTE, 13, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w")
        cfg = common.carregar_config()
        self.entry_porta = ctk.CTkEntry(col_porta, width=110, height=38,
                                        font=(common.FONTE, 14))
        self.entry_porta.insert(0, str(cfg.get("porta", common.PORTA_PADRAO)))
        self.entry_porta.pack(pady=(2, 0))

        col_perm = ctk.CTkFrame(linha2, fg_color="transparent")
        col_perm.pack(side="left", padx=(30, 0), anchor="s")
        self.var_escrita = ctk.BooleanVar(value=cfg.get("permitir_escrita", True))
        ctk.CTkSwitch(col_perm, text="Permitir gravacao (ler e escrever)",
                      variable=self.var_escrita, font=(common.FONTE, 13),
                      progress_color=common.COR_SUCESSO).pack(anchor="w", pady=(20, 0))

        # --- botao ligar/desligar
        self.btn_acao = ctk.CTkButton(
            painel, text="▶  INICIAR COMPARTILHAMENTO",
            font=(common.FONTE, 16, "bold"), height=52, corner_radius=12,
            fg_color=common.COR_SUCESSO, hover_color="#16a34a",
            command=self.alternar_servidor,
        )
        self.btn_acao.pack(fill="x", padx=20, pady=(14, 20))

        # Cartao de status / endereco
        self.painel_info = ctk.CTkFrame(self, fg_color=common.COR_PAINEL,
                                        corner_radius=16)
        self.painel_info.pack(fill="x", padx=24, pady=10)

        self.lbl_status = ctk.CTkLabel(
            self.painel_info, text="●  Parado",
            font=(common.FONTE, 15, "bold"), text_color=common.COR_ERRO,
        )
        self.lbl_status.pack(anchor="w", padx=20, pady=(16, 4))

        self.lbl_endereco = ctk.CTkLabel(
            self.painel_info,
            text="Endereco para a Estacao se conectar aparecera aqui.",
            font=(common.FONTE, 14), text_color=common.COR_TEXTO,
            justify="left",
        )
        self.lbl_endereco.pack(anchor="w", padx=20, pady=(0, 16))

        # Log
        ctk.CTkLabel(self, text="Registro de atividade",
                     font=(common.FONTE, 12, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=26)
        self.caixa_log = ctk.CTkTextbox(
            self, height=130, font=(common.FONTE_MONO, 12),
            fg_color="#0b0f18", text_color=common.COR_TEXTO_FRACO,
            corner_radius=12,
        )
        self.caixa_log.pack(fill="both", expand=True, padx=24, pady=(4, 22))
        self.caixa_log.configure(state="disabled")

    # ---- acoes ------------------------------------------------------------
    def atualizar_unidades(self):
        self.unidades = common.listar_unidades(incluir_fixas=False)
        if not self.unidades:
            self.combo_unidade.configure(values=["Nenhum pendrive detectado"])
            self.combo_unidade.set("Nenhum pendrive detectado")
            return
        rotulos = []
        for u in self.unidades:
            nome = u["rotulo"] or "Sem nome"
            rotulos.append(f"{u['letra']}:  ({nome})" if common.IS_WIN
                           else f"{u['raiz']}  ({nome})")
        self.combo_unidade.configure(values=rotulos)
        self.combo_unidade.set(rotulos[0])

    def _unidade_selecionada(self):
        texto = self.combo_unidade.get()
        if not texto or "Nenhum" in texto:
            return None
        if not common.IS_WIN:
            return texto.split("  (")[0].strip()
        letra = texto.split(":")[0].strip()
        return f"{letra}:\\"

    def alternar_servidor(self):
        if self.servidor.rodando:
            self.parar_servidor()
        else:
            self.iniciar_servidor()

    def iniciar_servidor(self):
        caminho = self._unidade_selecionada()
        if not caminho:
            messagebox.showwarning(common.APP_NAME,
                                   "Conecte um pendrive e clique em Atualizar.")
            return
        try:
            porta = int(self.entry_porta.get())
            if not (1 <= porta <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showwarning(common.APP_NAME, "Porta invalida.")
            return

        ok, msg = self.servidor.iniciar(caminho, porta, self.var_escrita.get())
        if not ok:
            self.adicionar_log(msg, "erro")
            messagebox.showerror(common.APP_NAME, msg)
            return

        common.salvar_config({
            "porta": porta,
            "permitir_escrita": self.var_escrita.get(),
        })

        self.adicionar_log(f"Compartilhando {caminho} na porta {porta}.", "ok")
        self._estado_ligado(caminho, porta)

    def parar_servidor(self):
        self.servidor.parar()
        self.adicionar_log("Compartilhamento parado.", "aviso")
        self._estado_desligado()

    def _estado_ligado(self, caminho, porta):
        ip = common.ip_local()
        self.lbl_status.configure(text="●  Compartilhando",
                                  text_color=common.COR_SUCESSO)
        self.lbl_endereco.configure(
            text=(f"Na Estacao, conecte usando:\n\n"
                  f"   Servidor:  {ip}\n"
                  f"   Porta:     {porta}\n\n"
                  f"Fora da rede: libere a porta {porta} no roteador\n"
                  f"e use o IP publico do seu PC.")
        )
        self.btn_acao.configure(text="■  PARAR COMPARTILHAMENTO",
                                fg_color=common.COR_ERRO, hover_color="#dc2626")
        self._travar_campos(True)

    def _estado_desligado(self):
        self.lbl_status.configure(text="●  Parado", text_color=common.COR_ERRO)
        self.lbl_endereco.configure(
            text="Endereco para a Estacao se conectar aparecera aqui.")
        self.btn_acao.configure(text="▶  INICIAR COMPARTILHAMENTO",
                                fg_color=common.COR_SUCESSO, hover_color="#16a34a")
        self._travar_campos(False)

    def _travar_campos(self, travar):
        estado = "disabled" if travar else "normal"
        self.combo_unidade.configure(state=estado)
        self.entry_porta.configure(state=estado)

    def adicionar_log(self, msg, nivel="info"):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        prefixo = {"ok": "[OK] ", "erro": "[ERRO] ",
                   "aviso": "[!] ", "info": ""}.get(nivel, "")
        self.caixa_log.configure(state="normal")
        self.caixa_log.insert("end", f"{hora}  {prefixo}{msg}\n")
        self.caixa_log.see("end")
        self.caixa_log.configure(state="disabled")

    def _ao_fechar(self):
        try:
            self.servidor.parar()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    AppServidor().mainloop()

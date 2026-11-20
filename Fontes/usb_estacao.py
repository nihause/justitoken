# -*- coding: utf-8 -*-
"""
usb_estacao.py - ESTACAO / CLIENTE (USB/IP)  -  JustiToken Estacao 3.0.3

v3.0.0 (16/10/2026): login na API JustiSoft, registro de auditoria, prazo de
uso de 1 hora definido pela API e reconexao automatica so com autorizacao
valida. O Servidor, o motor USB/IP e as portas 3240/3241 NAO foram alterados.

Roda no PC que vai USAR o dispositivo remoto.
Conecta no Servidor e ANEXA o USB (pendrive, HD, token, impressora...),
que passa a funcionar como se estivesse plugado neste computador.

Motor: usbip-win2 (cliente / driver VHCI).
Visual moderno com CustomTkinter.
"""

import os
import sys
import time
import threading
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common          # noqa: E402
import usbip_engine as eng  # noqa: E402
import bandeja          # noqa: E402
import atualizador   # noqa: E402

try:
    import customtkinter as ctk
    from tkinter import messagebox
except Exception as e:  # pragma: no cover
    print("CustomTkinter nao instalado. Rode o instalar.bat em C:\\usb.", e)
    sys.exit(1)

# ---- identidade da Estacao (common.py e o Servidor continuam intactos) ----
APP_NAME = "JustiToken"
VERSAO_ESTACAO = "3.0.3"
DATA_VERSAO_ESTACAO = "16/10/2026"
# Versao do Servidor com a qual esta Estacao conversa (protocolo da porta 3241).
VERSAO_SERVIDOR_COMPATIVEL = common.VERSAO
common.APP_NAME = APP_NAME            # so neste processo (titulo, rodape, bandeja)
common.VERSAO = VERSAO_ESTACAO
common.DATA_VERSAO = DATA_VERSAO_ESTACAO

import api_client as api      # noqa: E402
import sessao as ss           # noqa: E402
from tela_login import TelaLogin  # noqa: E402

INTERVALO_VERIFICACAO_MS = 60000  # confere a cada 60s se os tokens ainda sao desta estacao
INTERVALO_TICK_MS = 1000          # contagem regressiva das autorizacoes
INTERVALO_PENDENTES_MS = 60000    # reenvio de eventos guardados sem internet
AVISO_EXPIRACAO_S = 300           # avisa 5 minutos antes de expirar
TENTATIVAS_DESANEXAR = 5          # se a desanexacao por expiracao falhar


class AppEstacao(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{common.APP_NAME} v{common.VERSAO}  -  ESTACAO")
        try:
            common.aplicar_icone(self, "justitoken-estacao")
        except Exception:
            pass
        self.geometry("720x830")   # +70px para a barra de autorizacao
        self.minsize(660, 700)
        self.configure(fg_color=common.COR_FUNDO)

        self.sessao = None           # ss.Sessao do usuario logado
        self._autorizacoes = {}      # (servidor, busid) -> ss.Autorizacao
        self._geracao = 0            # muda a cada login/logout (para os ciclos after)
        self._ui_pronta = False
        self._saindo = False
        self._consulta_api_ok = True  # API oferece GET /token/autorizacao/<id>?
        self._tela_login = None
        self.bandeja = None
        self.protocol("WM_DELETE_WINDOW", self.encerrar)
        self._iniciar_autenticacao()

    # ---- autenticacao (antes da interface principal) ----------------------
    def _iniciar_autenticacao(self):
        """Usa a sessao salva (se 'Manter conectado') ou mostra a tela de login."""
        salva = None
        if common.carregar_config().get("manter_conectado", False):
            salva = ss.carregar_sessao()
        if not salva:
            self._mostrar_login()
            return
        if bandeja.DISPONIVEL:
            self.withdraw()  # como antes: inicia discreto; reaparece se precisar de login
        self._mostrar_login("Verificando sessão salva...")
        self._tela_login.ocupado(True, "Verificando...")

        def _t():
            erro = ""
            for tentativa in range(4):  # rede pode demorar a subir no logon
                try:
                    u = api.obter_usuario(salva.token)
                    if u.get("ativo") is False:
                        erro = "Usuário inativo. Procure o administrador."
                        break
                    if u.get("ativo") is None:
                        erro = "A API não confirmou que o usuário está ativo."
                        break
                    salva.usuario = {**salva.usuario,
                                     **{k: v for k, v in u.items() if v not in (None, "")}}
                    self.after(0, lambda: self._entrar(salva, True, automatico=True))
                    return
                except api.ErroApi as e:
                    erro = str(e)
                    if not e.sem_conexao:
                        break
                    time.sleep(5)
            if not erro.startswith("Sem conexao"):
                ss.apagar_sessao()
            self.after(0, lambda: self._falha_sessao_salva(erro))
        threading.Thread(target=_t, daemon=True).start()

    def _falha_sessao_salva(self, erro):
        if self._tela_login is None:
            return
        self._tela_login.ocupado(False)
        self._tela_login.mensagem(f"Entre novamente. ({erro})" if erro
                                  else "Entre novamente.", common.COR_AVISO)
        self.mostrar_janela()

    def _mostrar_login(self, mensagem=""):
        self._tela_login = TelaLogin(self, self._entrar, mensagem)
        self._tela_login.pack(fill="both", expand=True)

    def _entrar(self, sessao_nova, manter, senha="", automatico=False):
        """Login aprovado (usuario ativo): libera a interface principal."""
        self.sessao = sessao_nova
        if manter and senha:
            self.sessao.senha = senha
        if manter:
            if not ss.salvar_sessao(sessao_nova):
                common.registrar_log("ESTACAO", "[!] Nao foi possivel guardar a sessao.")
        else:
            # Sessao expirada nao apaga a senha que o usuario escolheu salvar;
            # ela continua protegida por DPAPI para o proximo login manual.
            ss.limpar_token_salvo()
        if self._tela_login is not None:
            self._tela_login.destroy()
            self._tela_login = None
        self._iniciar_pos_login(automatico)
        self.log(f"Usuario {self.sessao.nome} conectado"
                 f"{' (sessao salva)' if automatico else ''}.", "ok")
        self._evento(api.EV_LOGIN, "SUCESSO",
                     detalhe="sessao_salva" if automatico else "usuario_senha")
        self._iniciar_reenvio_pendentes()

    def _iniciar_pos_login(self, automatico=False):
        """Exatamente o que a Estacao fazia ao abrir, agora depois do login."""
        self._geracao += 1
        g = self._geracao
        self._em_andamento = set()   # busids sendo anexados agora
        self._perdidos = set()       # (servidor, busid, porta) que outro PC tomou
        self._info = {}              # servidor -> resposta de consultar_servidor
        self._versao_avisada = set()
        self._ultimos_anexados = []
        self._lbl_tempo = {}         # (servidor, busid) -> label do tempo no cartao
        self._saindo = False
        # inclui as ja vencidas: o ciclo de 1s encerra e desanexa na hora
        self._autorizacoes = {a.chave: a for a in
                              ss.carregar_autorizacoes(self.sessao.usuario,
                                                       incluir_vencidas=True)}
        self._montar_ui()
        self._ui_pronta = True
        self.after(300, self.verificar_cliente)
        self.after(4000, lambda: atualizador.verificar_em_segundo_plano(self, self.log))
        self.after(INTERVALO_VERIFICACAO_MS, lambda: self._verificar_periodico(g))
        self.after(INTERVALO_TICK_MS, lambda: self._tick_autorizacoes(g))
        self.after(INTERVALO_PENDENTES_MS, lambda: self._ciclo_pendentes(g))
        self._configurar_bandeja(esconder=automatico)
        if not automatico:
            self.mostrar_janela()

    # ---- bandeja (icone perto do relogio) --------------------------------
    def _configurar_bandeja(self, esconder=True):
        if self.bandeja is None:
            self.bandeja = bandeja.Bandeja(
                self, f"{common.APP_NAME} - Estacao", cor=common.COR_DESTAQUE,
                tipo="estacao")
            if bandeja.DISPONIVEL:
                self.bandeja.iniciar()
        if bandeja.DISPONIVEL:
            self.protocol("WM_DELETE_WINDOW", self.esconder_janela)
            if esconder:
                self.withdraw()  # inicia minimizado na bandeja
        else:
            self.protocol("WM_DELETE_WINDOW", self.encerrar)

    def _notificar(self, msg):
        """Balao do Windows pelo icone da bandeja (se disponivel)."""
        try:
            if self.bandeja and self.bandeja.icone:
                self.bandeja.icone.notify(msg, common.APP_NAME)
        except Exception:
            pass

    def mostrar_janela(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def esconder_janela(self):
        self.withdraw()

    def encerrar(self):
        try:
            if self.bandeja:
                self.bandeja.parar()
        except Exception:
            pass
        self.destroy()

    # ---- UI ---------------------------------------------------------------
    def _montar_ui(self):
        cfg = common.carregar_config()

        # Rodape primeiro, para ficar sempre visivel no fundo
        self.lbl_status = common.criar_rodape(self)
        self._n_anexados = 0
        self.after(800, self._atualizar_status)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(16, 8))

        # A conta fica numa linha exclusiva: nomes longos nao se sobrepoem ao titulo.
        caixa_usr = ctk.CTkFrame(topo, fg_color="transparent")
        caixa_usr.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(caixa_usr, text="Sair da conta", width=110, height=30,
                      font=(common.FONTE, 12),
                      fg_color=common.COR_PAINEL, hover_color=common.COR_ERRO,
                      command=self.sair_da_conta).pack(side="right")
        ctk.CTkButton(caixa_usr, text="Trocar usuário", width=112, height=30,
                      font=(common.FONTE, 12), fg_color=common.COR_PAINEL,
                      hover_color=common.COR_DESTAQUE2,
                      command=self.trocar_usuario).pack(side="right", padx=(0, 8))
        self.lbl_usuario = ctk.CTkLabel(
            caixa_usr, text=f"👤 {self.sessao.nome if self.sessao else ''}",
            font=(common.FONTE, 13, "bold"), text_color=common.COR_TEXTO)
        self.lbl_usuario.pack(side="right", padx=(0, 10))

        # Marca do produto abaixo da conta, em um bloco proprio e mais legivel.
        cabecalho_produto = ctk.CTkFrame(topo, fg_color=common.COR_PAINEL,
                                         corner_radius=14)
        cabecalho_produto.pack(fill="x")
        ctk.CTkLabel(cabecalho_produto, text=f"🔑  {common.APP_NAME}  •  Estação",
                     font=(common.FONTE, 24, "bold"),
                     text_color=common.COR_TEXTO).pack(anchor="w", padx=18, pady=(12, 0))
        ctk.CTkLabel(cabecalho_produto,
                     text="Anexe aqui os tokens / dispositivos USB do computador servidor.",
                     font=(common.FONTE, 13),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=18,
                                                              pady=(2, 12))

        # Status da autorizacao de uso (tempo restante / aviso de expiracao)
        self.barra_aut = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=12)
        self.barra_aut.pack(fill="x", padx=24, pady=(4, 2))
        self.lbl_aut = ctk.CTkLabel(self.barra_aut, text="Autorização: nenhuma ativa",
                                    font=(common.FONTE, 13, "bold"), anchor="w",
                                    justify="left", text_color=common.COR_TEXTO_FRACO)
        self.lbl_aut.pack(fill="x", padx=16, pady=8)

        # Banner de instalacao do cliente
        self.banner = ctk.CTkFrame(self, fg_color="#3a2a12", corner_radius=12)
        self.lbl_banner = ctk.CTkLabel(
            self.banner, text="Verificando cliente USB/IP...",
            font=(common.FONTE, 13),
            text_color=common.COR_AVISO, justify="left")
        self.lbl_banner.pack(side="left", padx=16, pady=12)
        self.btn_banner = ctk.CTkButton(
            self.banner, text="Instalar cliente", width=160,
            fg_color=common.COR_AVISO, hover_color="#d97706",
            text_color="#1a1206", font=(common.FONTE, 13, "bold"),
            command=self.instalar_cliente)
        self.btn_banner.pack(side="right", padx=12, pady=10)
        # fixa a faixa no topo desde ja (sera escondida se o cliente existir)
        self.banner.pack(fill="x", padx=24, pady=(4, 6))

        # Conexao
        self.painel = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=16)
        painel = self.painel
        painel.pack(fill="x", padx=24, pady=10)
        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(linha, text="Servidor:", font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO_FRACO).pack(side="left")
        self.entry_servidor = ctk.CTkEntry(linha, height=40,
                                           placeholder_text="ex: 192.168.0.10",
                                           font=(common.FONTE, 14))
        self.entry_servidor.insert(0, cfg.get("ultimo_servidor", ""))
        self.entry_servidor.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkButton(linha, text="🔍  Buscar dispositivos", width=190, height=40,
                      font=(common.FONTE, 13, "bold"),
                      fg_color=common.COR_DESTAQUE, hover_color=common.COR_DESTAQUE2,
                      command=self.buscar).pack(side="left")

        # Opcoes: auto-conectar + iniciar com o Windows
        op = ctk.CTkFrame(painel, fg_color="transparent")
        op.pack(fill="x", padx=20, pady=(0, 14))
        self.var_auto = ctk.BooleanVar(value=bool(cfg.get("auto_conectar", False)))
        ctk.CTkSwitch(op, text="Reconectar automaticamente ao iniciar",
                      variable=self.var_auto, font=(common.FONTE, 13),
                      progress_color=common.COR_SUCESSO,
                      command=self._salvar_auto).pack(side="left")
        ctk.CTkButton(op, text=common.TXT_INICIAR_SISTEMA, width=250,
                      font=(common.FONTE, 12),
                      fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
                      command=self.configurar_inicio).pack(side="right")

        # Lista de dispositivos remotos
        ctk.CTkLabel(self, text="Dispositivos disponiveis no servidor",
                     font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO).pack(anchor="w", padx=26, pady=(6, 0))
        self.lista_remota = ctk.CTkScrollableFrame(self, fg_color=common.COR_PAINEL,
                                                   corner_radius=16, height=180)
        self.lista_remota.pack(fill="both", expand=True, padx=24, pady=(4, 6))

        # Lista de anexados
        cab = ctk.CTkFrame(self, fg_color="transparent")
        cab.pack(fill="x", padx=26, pady=(2, 0))
        ctk.CTkLabel(cab, text="Anexados nesta estacao",
                     font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO).pack(side="left")
        ctk.CTkButton(cab, text="↻", width=40,
                      fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
                      command=self._verificar_agora).pack(side="right")
        self.lista_anexada = ctk.CTkScrollableFrame(self, fg_color=common.COR_PAINEL,
                                                    corner_radius=16, height=120)
        self.lista_anexada.pack(fill="both", expand=True, padx=24, pady=(4, 6))

        # Log
        self.caixa_log = ctk.CTkTextbox(self, height=100, font=(common.FONTE_MONO, 12),
                                        fg_color="#0b0f18",
                                        text_color=common.COR_TEXTO_FRACO,
                                        corner_radius=12)
        self.caixa_log.pack(fill="x", padx=24, pady=(0, 8))
        self.caixa_log.configure(state="disabled")

    # ---- logica -----------------------------------------------------------
    def _salvar_auto(self):
        common.salvar_config({"auto_conectar": self.var_auto.get()})
        self.log(f"Reconexao automatica {'ligada' if self.var_auto.get() else 'desligada'}.",
                 "info")

    def configurar_inicio(self):
        alvo = sys.executable if getattr(sys, "frozen", False) \
            else os.path.abspath(__file__)
        self.var_auto.set(True)
        common.salvar_config({"auto_conectar": True})
        self.log(common.TXT_CONFIG_INICIO, "info")

        def _t():
            ok = eng.criar_tarefa_inicio("USBRede_Estacao", alvo)
            self.after(0, lambda: self.log(
                "Pronto! Vai abrir e reconectar sozinho no logon (sem UAC)." if ok
                else "Falha ao criar a tarefa de inicio.",
                "ok" if ok else "erro"))
        threading.Thread(target=_t, daemon=True).start()

    def auto_reconectar(self):
        """Reanexa ao iniciar SOMENTE os dispositivos com autorizacao ainda valida
        deste usuario (sem autorizacao, a reconexao automatica fica desativada)."""
        cfg = common.carregar_config()
        servidor = str(cfg.get("ultimo_servidor", "") or "")
        disp = common.get_lista(cfg, "dispositivos")
        if not servidor or not disp:
            return
        validos, ignorados = [], []
        for b in disp:
            a = self._autorizacoes.get((servidor, b))
            (validos if a and not a.encerrada and not a.expirada() else ignorados).append(b)
        if ignorados:
            self.log(f"Reconexao automatica ignorada para {', '.join(ignorados)}: "
                     f"sem autorizacao valida. Clique em Anexar para solicitar.", "aviso")
            common.salvar_config({"dispositivos": ",".join(validos)})
        if not validos:
            return
        self.log(f"Auto-conectar: anexando {len(validos)} dispositivo(s) autorizado(s) "
                 f"de {servidor}...", "info")

        def _t():
            for b in validos:
                ok, msg = eng.anexar(servidor, b)
                a = self._autorizacoes.get((servidor, b))
                self._evento(api.EV_RECONEXAO, "SUCESSO" if ok else "FALHA",
                             a.dispositivo() if a else self._dispositivo(servidor, b),
                             detalhe=msg, aut_id=a.autorizacao_id if a else None)
            self.after(0, self.atualizar_anexados)
        threading.Thread(target=_t, daemon=True).start()

    def verificar_cliente(self):
        self.log(f"{common.APP_NAME} v{common.VERSAO} ({common.DATA_VERSAO}).", "info")
        if eng.cliente_instalado():
            self.banner.pack_forget()
            self.log("Cliente USB/IP detectado.", "ok")
            self.atualizar_anexados()
            # Auto-listar: se o IP do servidor ja esta preenchido, busca sozinho
            if self.entry_servidor.get().strip():
                self.log("Listando dispositivos do servidor automaticamente...", "info")
                self.buscar()
            if self.var_auto.get():
                self.auto_reconectar()
        else:
            self.lbl_banner.configure(
                text=f"Cliente USB/IP ({common.MOTOR_CLIENTE}) nao instalado.\n"
                     "Clique em 'Instalar cliente'" + common.TXT_REINICIO)
            self.banner.pack(fill="x", padx=24, pady=(4, 6), before=self.painel)
            self.log("Cliente nao instalado. Clique em 'Instalar cliente'.", "aviso")

    def instalar_cliente(self):
        self.btn_banner.configure(text="Instalando...", state="disabled")
        self.log("Baixando e instalando o cliente USB/IP...", "info")

        def _prog(txt):
            self.after(0, lambda: self.log(txt, "info"))

        def _t():
            ok, msg = eng.instalar_cliente(destino_dir=common.PASTA_BASE,
                                           progresso=_prog)
            self.after(0, lambda: self._fim_instalar_cliente(ok, msg))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_instalar_cliente(self, ok, msg):
        self.btn_banner.configure(text="Instalar cliente", state="normal")
        self.log(msg, "ok" if ok else "erro")
        if ok:
            self.verificar_cliente()
        else:
            messagebox.showwarning(common.APP_NAME, msg)

    # ---- info do servidor (versao, nomes, quem usa) ----------------------
    def _guardar_info(self, servidor, info):
        """Guarda a resposta do servidor e avisa uma vez se a versao for diferente."""
        if info is None:
            return
        self._info[servidor] = info
        if servidor in self._versao_avisada:
            return
        versao = info.get("versao")
        if versao != VERSAO_SERVIDOR_COMPATIVEL:
            self._versao_avisada.add(servidor)
            self.log(f"Servidor {servidor} esta na versao {versao or 'antiga'}; esta "
                     f"Estacao ({common.VERSAO}) foi feita para o Servidor "
                     f"{VERSAO_SERVIDOR_COMPATIVEL}.", "aviso")

    def _nome_de(self, servidor, busid, padrao=""):
        d = self._info.get(servidor, {}).get("dispositivos", {}).get(busid) or {}
        return d.get("nome") or padrao

    def buscar(self, silencioso=False):
        if not self._ui_pronta:
            return
        servidor = self.entry_servidor.get().strip()
        if not servidor:
            if not silencioso:
                messagebox.showwarning(common.APP_NAME, "Informe o IP do servidor.")
            return
        if not eng.cliente_instalado():
            if not silencioso:
                messagebox.showwarning(common.APP_NAME,
                                       "Instale o cliente USB/IP primeiro.")
            return
        if not silencioso:
            common.salvar_config({"ultimo_servidor": servidor})
            self.log(f"Buscando dispositivos em {servidor}...", "info")

        def _t():
            disp = eng.listar_dispositivos_remotos(servidor)
            info = eng.consultar_servidor(servidor)
            self.after(0, lambda: self._mostrar_remotos(servidor, disp, info, silencioso))
        threading.Thread(target=_t, daemon=True).start()

    def _mostrar_remotos(self, servidor, disp, info=None, silencioso=False):
        if not self._ui_pronta:
            return
        self._guardar_info(servidor, info)
        if info:
            self._mostrar_anexados(self._ultimos_anexados)  # atualiza os nomes
        for w in self.lista_remota.winfo_children():
            w.destroy()
        # O que ja esta anexado nesta Estacao pertence apenas ao quadro abaixo.
        # Assim o mesmo token nao aparece simultaneamente como "disponivel".
        servidor_normalizado = str(servidor or "").strip().lower()
        anexados_aqui = {
            a.get("busid") for a in self._ultimos_anexados
            if a.get("busid") and (
                not a.get("servidor")
                or str(a.get("servidor")).strip().lower() == servidor_normalizado
            )
        }
        disp_disponiveis = [d for d in disp if d.get("busid") not in anexados_aqui]

        if not disp_disponiveis:
            texto_vazio = ("Todos os dispositivos compartilhados deste servidor "
                           "ja estao anexados nesta Estacao."
                           if disp and anexados_aqui else
                           "Nenhum dispositivo compartilhado encontrado.\n"
                           "Confira o IP, o firewall e se o servidor compartilhou algo.")
            ctk.CTkLabel(self.lista_remota,
                         text=texto_vazio,
                         font=(common.FONTE, 13),
                         text_color=common.COR_TEXTO_FRACO).pack(pady=16)
            if not silencioso:
                self.log("Nenhum dispositivo disponivel para anexar.", "aviso")
            return
        if not silencioso:
            ocultos = len(disp) - len(disp_disponiveis)
            sufixo = f" ({ocultos} ja anexado(s) nesta Estacao)" if ocultos else ""
            self.log(f"{len(disp_disponiveis)} dispositivo(s) disponivel(is).{sufixo}", "ok")
        for d in disp_disponiveis:
            self._linha_remota(servidor, d, info)

    def _linha_remota(self, servidor, d, info=None):
        extra = (info or {}).get("dispositivos", {}).get(d["busid"]) or {}
        nome = extra.get("nome") or ""

        cartao = ctk.CTkFrame(self.lista_remota, fg_color=common.COR_FUNDO,
                              corner_radius=12)
        cartao.pack(fill="x", padx=8, pady=6)
        # botoes primeiro (lado direito), para nunca serem espremidos pelo texto
        ctk.CTkButton(cartao, text="⬇  Anexar", width=110, height=36,
                      font=(common.FONTE, 13, "bold"),
                      fg_color=common.COR_SUCESSO, hover_color="#16a34a",
                      command=lambda: self.anexar(servidor, d["busid"])
                      ).pack(side="right", padx=(6, 14), pady=10)
        ctk.CTkButton(cartao, text="⚡ Forcar", width=90, height=36,
                      font=(common.FONTE, 13, "bold"),
                      fg_color=common.COR_AVISO, hover_color="#d97706",
                      text_color="#1a1206",
                      command=lambda: self.forcar(servidor, d["busid"])
                      ).pack(side="right", padx=0, pady=10)

        esq = ctk.CTkFrame(cartao, fg_color="transparent")
        esq.pack(side="left", fill="x", expand=True, padx=14, pady=8)
        ctk.CTkLabel(esq, text=nome or d["descricao"], font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO, anchor="w").pack(anchor="w")
        sub = f"BUSID {d['busid']}"
        if nome:
            sub += f"  •  {d['descricao']}"
        ctk.CTkLabel(esq, text=sub, font=(common.FONTE, 11),
                     text_color=common.COR_TEXTO_FRACO, anchor="w").pack(anchor="w")
        if extra:
            if not extra.get("em_uso"):
                estado, cor = "● livre", common.COR_SUCESSO
            elif extra.get("cliente") == info.get("voce"):
                estado, cor = "● em uso por ESTA estação", common.COR_DESTAQUE
            else:
                estado, cor = f"● em uso por {extra.get('cliente')}", common.COR_AVISO
            ctk.CTkLabel(esq, text=estado, font=(common.FONTE, 11, "bold"),
                         text_color=cor, anchor="w").pack(anchor="w")

    # ---- anexar / forcar --------------------------------------------------
    def anexar(self, servidor, busid, forcar_antes=False):
        """Anexa nesta estacao. Se outro computador estiver usando, derruba o
        uso dele e anexa aqui."""
        if not eng.cliente_instalado():
            messagebox.showwarning(common.APP_NAME,
                                   "Instale o cliente USB/IP primeiro.")
            return
        if busid in self._em_andamento:
            self.log(f"{busid}: ja estou anexando, aguarde...", "aviso")
            return
        if not self.sessao:
            return
        self._em_andamento.add(busid)
        rotulo = self._nome_de(servidor, busid, busid)
        disp = self._dispositivo(servidor, busid)
        sessao_atual = self.sessao
        self.log(f"Solicitando autorizacao para {rotulo}...", "info")

        def _t():
            # 1) registra a SOLICITACAO_TOKEN_USB na API e recebe a autorizacao
            try:
                autorizado, dados, msg_api = api.solicitar_token(
                    sessao_atual, disp, "FORCAR" if forcar_antes else "ANEXAR")
            except api.ErroApi as e:
                msg_erro, expirou = str(e), e.nao_autorizado
                self.after(0, lambda: self._anexar_negado(
                    servidor, busid, msg_erro, sessao_expirada=expirou))
                return
            except Exception as e:  # nunca deixar o busid preso em _em_andamento
                msg_erro = f"erro inesperado: {e}"
                self.after(0, lambda: self._anexar_negado(servidor, busid, msg_erro))
                return
            if not autorizado:
                self.after(0, lambda: self._anexar_negado(servidor, busid, msg_api))
                return
            # o prazo conta a partir da concessao (agora), nao do fim do attach
            dados["deadline_epoch"] = time.time() + dados["segundos"]
            self.after(0, lambda: self._autorizacao_concedida(rotulo, dados,
                                                              forcar_antes, servidor))

            # 2) rotina existente, sem alteracao
            def _prog(txt):
                self.after(0, lambda: self.log(txt, "info"))

            ok, msg, tomou = eng.tomar_dispositivo(
                servidor, busid, progresso=_prog, forcar_antes=forcar_antes)

            # 3) registra o resultado
            self._evento(api.EV_ANEXADO if ok else api.EV_FALHA_ANEXO,
                         "SUCESSO" if ok else "FALHA", disp,
                         detalhe=(("uso anterior derrubado. " if tomou else "") + (msg or ""))
                         .strip(), aut_id=dados.get("autorizacao_id"),
                         sessao_ev=sessao_atual)
            self.after(0, lambda: self._fim_anexar(ok, servidor, busid, msg, tomou, dados))
        threading.Thread(target=_t, daemon=True).start()

    def _autorizacao_concedida(self, rotulo, dados, forcar_antes, servidor):
        if dados.get("origem") == "padrao":
            self.log("A API nao informou o horario de expiracao; contando 60 minutos "
                     "a partir da concessao.", "aviso")
        self.log(f"Autorizacao concedida para {rotulo}: "
                 f"{ss.formatar_tempo(dados['segundos'])} de uso.", "ok")
        if forcar_antes:
            self.log(f"Forcando {rotulo}: derrubando quem estiver usando...", "info")
        else:
            self.log(f"Anexando {rotulo} de {servidor} (vai pedir admin)...", "info")

    def _anexar_negado(self, servidor, busid, msg, sessao_expirada=False):
        self._em_andamento.discard(busid)
        rotulo = self._nome_de(servidor, busid, busid)
        if sessao_expirada:
            self._sessao_expirada()
            return
        self.log(f"Uso de {rotulo} NAO autorizado: {msg}", "erro")
        messagebox.showwarning(common.APP_NAME,
                               f"Não foi possível obter autorização para {rotulo}.\n\n{msg}")

    def _fim_anexar(self, ok, servidor, busid, msg="", tomou=False, dados=None):
        self._em_andamento.discard(busid)
        rotulo = self._nome_de(servidor, busid, busid)
        if ok and dados is not None and self.sessao:
            a = ss.Autorizacao(
                servidor, busid, self.sessao.usuario.get("id"),
                self.sessao.usuario.get("login"), dados["segundos"],
                autorizacao_id=dados.get("autorizacao_id"),
                nome=self._nome_de(servidor, busid, ""),
                descricao=self._descricao_de(servidor, busid),
                expira_em_api=dados.get("expira_em_api", ""),
                deadline_epoch=dados.get("deadline_epoch"))
            self._autorizacoes[a.chave] = a
            self._salvar_autorizacoes()
        if ok:
            # salva no ini para reconexao automatica no proximo inicio
            disp = common.get_lista(common.carregar_config(), "dispositivos")
            if busid not in disp:
                disp.append(busid)
            common.salvar_config({"ultimo_servidor": servidor,
                                  "dispositivos": ",".join(disp)})
            self._perdidos = {p for p in self._perdidos if p[1] != busid}
            extra = " Uso anterior foi derrubado." if tomou else ""
            self.log(f"{rotulo} anexado!{extra} Veja em 'Este Computador' / Dispositivos.",
                     "ok")
            a = self._autorizacoes.get((servidor, busid))
            if a:
                self.log(f"Uso autorizado ate {a.hora_expiracao()} "
                         f"(sem renovacao automatica).", "info")
        else:
            detalhe = f"  ({msg})" if msg else ""
            self.log(f"Falha ao anexar {rotulo}.{detalhe}", "erro")
        self.atualizar_anexados()
        self.buscar(silencioso=True)

    def forcar(self, servidor, busid):
        """Derruba quem estiver usando o dispositivo e anexa nesta estacao."""
        self.anexar(servidor, busid, forcar_antes=True)

    # ---- anexados + verificacao periodica --------------------------------
    def atualizar_anexados(self):
        if not eng.cliente_instalado():
            self._mostrar_anexados([])
            return
        self._mostrar_anexados(eng.listar_anexados())

    def _mostrar_anexados(self, anex):
        if not self._ui_pronta:
            return
        self._ultimos_anexados = anex
        self._lbl_tempo = {}
        # esquece perdidos cuja porta ja sumiu do cliente
        chaves = {(a["servidor"], a["busid"], a["porta"]) for a in anex}
        self._perdidos &= chaves
        anex = [a for a in anex
                if (a["servidor"], a["busid"], a["porta"]) not in self._perdidos]

        for w in self.lista_anexada.winfo_children():
            w.destroy()
        self._n_anexados = len(anex)
        if not anex:
            ctk.CTkLabel(self.lista_anexada, text="Nenhum dispositivo anexado.",
                         font=(common.FONTE, 13),
                         text_color=common.COR_TEXTO_FRACO).pack(pady=14)
            return
        for a in anex:
            self._linha_anexada(a)

    def _iniciar_checagem(self):
        if not self._ui_pronta:
            return
        if eng.cliente_instalado():
            threading.Thread(target=self._checar_posse,
                             args=(self.entry_servidor.get().strip(),),
                             daemon=True).start()
        self._iniciar_consulta_autorizacoes()

    def _verificar_agora(self):
        self.atualizar_anexados()
        self._iniciar_checagem()

    def _verificar_periodico(self, g=None):
        """A cada 60s: confere no servidor se cada token anexado aqui ainda e
        desta estacao. Se outro computador pegou, tira da lista."""
        if g is not None and g != self._geracao:
            return  # houve logout: este ciclo para
        self._iniciar_checagem()
        self.after(INTERVALO_VERIFICACAO_MS, lambda: self._verificar_periodico(g))

    def _checar_posse(self, principal=""):
        """Roda em thread (sem mexer na interface)."""
        anex = eng.listar_anexados()
        infos = {}
        for srv in {a["servidor"] for a in anex if a["servidor"]}:
            infos[srv] = eng.consultar_servidor(srv)
        if principal and principal not in infos:
            infos[principal] = eng.consultar_servidor(principal)

        perdidos = []
        for a in anex:
            if not a["busid"] or a["busid"] in self._em_andamento:
                continue
            info = infos.get(a["servidor"])
            if not info or not info.get("versao"):
                continue  # servidor fora do ar ou versao antiga: nao mexe
            d = info["dispositivos"].get(a["busid"])
            if d is None:
                continue  # dispositivo reiniciando / sumiu: confere na proxima
            if d.get("cliente") != info.get("voce"):
                if eng.eh_admin():
                    eng.desanexar(a["porta"])  # limpa a porta local sem UAC
                perdidos.append((a, d.get("cliente") or ""))

        anex_depois = eng.listar_anexados() if perdidos else anex
        self.after(0, lambda: self._fim_checar_posse(infos, perdidos, anex_depois))

    def _fim_checar_posse(self, infos, perdidos, anex):
        if not self._ui_pronta:
            return
        for srv, info in infos.items():
            self._guardar_info(srv, info)
        if perdidos:
            disp = common.get_lista(common.carregar_config(), "dispositivos")
            for a, cliente in perdidos:
                aut = self._autorizacoes.pop((a["servidor"], a["busid"]), None)
                if aut:
                    aut.encerrada = True
                    self._salvar_autorizacoes()
                self._evento(api.EV_PERDA, "PERDIDO",
                             aut.dispositivo() if aut else
                             self._dispositivo(a["servidor"], a["busid"]),
                             detalhe=(f"agora com {cliente}" if cliente
                                      else "desconectado pelo servidor"),
                             aut_id=aut.autorizacao_id if aut else None)
                self._perdidos.add((a["servidor"], a["busid"], a["porta"]))
                if a["busid"] in disp:
                    disp.remove(a["busid"])
                rotulo = self._nome_de(a["servidor"], a["busid"],
                                       a["descricao"] or a["busid"])
                quem = f"agora esta com {cliente}" if cliente else "foi desconectado"
                self.log(f"{rotulo} nao esta mais nesta estacao ({quem}). "
                         f"Removido de 'Anexados'.", "aviso")
            common.salvar_config({"dispositivos": ",".join(disp)})
        self._mostrar_anexados(anex)
        try:
            if self.winfo_viewable():
                self.buscar(silencioso=True)
        except Exception:
            pass

    def _linha_anexada(self, a):
        cartao = ctk.CTkFrame(self.lista_anexada, fg_color=common.COR_FUNDO,
                              corner_radius=12)
        cartao.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(cartao, text="⏏  Desanexar", width=130, height=36,
                      font=(common.FONTE, 13, "bold"),
                      fg_color=common.COR_ERRO, hover_color="#dc2626",
                      command=lambda: self.desanexar(a["porta"], a.get("busid", ""),
                                                     a.get("servidor", ""))
                      ).pack(side="right", padx=14, pady=10)
        esq = ctk.CTkFrame(cartao, fg_color="transparent")
        esq.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        desc = a["descricao"] or "Dispositivo USB"
        nome = self._nome_de(a["servidor"], a["busid"])
        ctk.CTkLabel(esq, text=nome or desc, font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO, anchor="w").pack(anchor="w")
        sub = f"Porta {a['porta']}"
        if nome:
            sub += f"   •   {desc}"
        ctk.CTkLabel(esq, text=sub, font=(common.FONTE, 11),
                     text_color=common.COR_TEXTO_FRACO, anchor="w").pack(anchor="w")
        # tempo restante da autorizacao (atualizado a cada segundo)
        chave = (a["servidor"], a["busid"])
        lbl = ctk.CTkLabel(esq, text="", font=(common.FONTE, 11, "bold"),
                           text_color=common.COR_TEXTO_FRACO, anchor="w")
        lbl.pack(anchor="w")
        self._lbl_tempo[chave] = lbl
        self._atualizar_lbl_tempo(chave, lbl)

    def desanexar(self, porta, busid="", servidor=""):
        self.log(f"Desanexando porta {porta} (vai pedir admin)...", "info")

        def _t():
            ok, msg = eng.desanexar(porta)
            self.after(0, lambda: self._fim_desanexar(ok, porta, busid, servidor, msg))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_desanexar(self, ok, porta, busid="", servidor="", msg=""):
        if busid:
            aut = self._autorizacoes.get((servidor, busid)) if servidor else None
            if aut is None:
                aut = next((x for x in self._autorizacoes.values() if x.busid == busid),
                           None)
            if ok and aut:
                aut.encerrada = True
                self._autorizacoes.pop(aut.chave, None)
                self._salvar_autorizacoes()
            self._evento(api.EV_DESANEXADO, "SUCESSO" if ok else "FALHA",
                         aut.dispositivo() if aut else self._dispositivo(servidor, busid),
                         detalhe=("liberacao voluntaria" + (f" - {msg}" if msg and not ok
                                                            else "")),
                         aut_id=aut.autorizacao_id if aut else None)
        if ok and busid:
            disp = common.get_lista(common.carregar_config(), "dispositivos")
            if busid in disp:
                disp.remove(busid)
                common.salvar_config({"dispositivos": ",".join(disp)})
        self.log(
            f"Porta {porta} desanexada." if ok else f"Falha ao desanexar {porta}.",
            "ok" if ok else "erro")
        self.atualizar_anexados()

    def log(self, msg, nivel="info"):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        prefixo = {"ok": "[OK] ", "erro": "[ERRO] ",
                   "aviso": "[!] ", "info": ""}.get(nivel, "")
        try:
            self.caixa_log.configure(state="normal")
            self.caixa_log.insert("end", f"{hora}  {prefixo}{msg}\n")
            self.caixa_log.see("end")
            self.caixa_log.configure(state="disabled")
        except Exception:
            pass  # interface ainda nao montada (tela de login) ou ja desmontada
        common.registrar_log("ESTACAO", f"{prefixo}{msg}")

    # ======================================================================
    #  JustiToken 3.0 - autorizacao de uso, auditoria e sessao
    # ======================================================================
    def _descricao_de(self, servidor, busid):
        d = self._info.get(servidor, {}).get("dispositivos", {}).get(busid) or {}
        if d.get("descricao"):
            return d["descricao"]
        for a in self._ultimos_anexados:
            if a.get("servidor") == servidor and a.get("busid") == busid:
                return a.get("descricao", "")
        return ""

    def _dispositivo(self, servidor, busid):
        return {"servidor": servidor, "busid": busid,
                "nome": self._nome_de(servidor, busid, ""),
                "descricao": self._descricao_de(servidor, busid)}

    def _evento(self, evento, status, dispositivo=None, detalhe="", aut_id=None,
                sessao_ev=None, extra=None):
        """Envia um evento de auditoria em thread (fila offline se sem internet)."""
        s = sessao_ev or self.sessao
        if s is None:
            return
        ev = api.montar_evento(evento, status, s, dispositivo, detalhe, aut_id, extra)
        d = ev["dispositivo"]
        common.registrar_log(
            "ESTACAO", f"[AUDITORIA] {evento} {status} usuario={s.usuario.get('login')} "
                       f"computador={ev['computador']} disp={d.get('servidor')}/"
                       f"{d.get('busid')} {detalhe or ''}".rstrip())

        def _t():
            try:
                api.enviar_evento(s, ev)
            except api.ErroApi as e:
                if e.nao_autorizado and s is self.sessao:
                    self.after(0, self._sessao_expirada)
            except Exception:
                pass
        if threading.current_thread() is threading.main_thread():
            threading.Thread(target=_t, daemon=True).start()
        else:
            _t()

    def _salvar_autorizacoes(self):
        ss.salvar_autorizacoes(list(self._autorizacoes.values()))

    # ---- contagem regressiva (1 s) ---------------------------------------
    def _tick_autorizacoes(self, g):
        if g != self._geracao:
            return
        try:
            for a in list(self._autorizacoes.values()):
                if a.encerrada:
                    continue
                rest = a.segundos_restantes()
                if rest <= 0:
                    self._encerrar_por_expiracao(a)
                elif rest <= AVISO_EXPIRACAO_S and not a.avisada:
                    a.avisada = True
                    rotulo = a.nome or a.descricao or a.busid
                    msg = (f"A autorizacao de {rotulo} expira em "
                           f"{ss.formatar_tempo(rest)} (as {a.hora_expiracao()}). "
                           f"Conclua as assinaturas.")
                    self.log(msg, "aviso")
                    self._notificar(msg)
            for chave, lbl in list(self._lbl_tempo.items()):
                self._atualizar_lbl_tempo(chave, lbl)
            self._atualizar_barra_aut()
        except Exception:
            pass
        self.after(INTERVALO_TICK_MS, lambda: self._tick_autorizacoes(g))

    def _atualizar_lbl_tempo(self, chave, lbl):
        a = self._autorizacoes.get(chave)
        try:
            if not a or a.encerrada:
                lbl.configure(text="Autorização: sem autorização registrada nesta sessão",
                              text_color=common.COR_TEXTO_FRACO)
                return
            rest = a.segundos_restantes()
            cor = common.COR_AVISO if rest <= AVISO_EXPIRACAO_S else common.COR_SUCESSO
            lbl.configure(text=f"Autorização ativa  •  restam {ss.formatar_tempo(rest)}"
                               f"  (até {a.hora_expiracao()})", text_color=cor)
        except Exception:
            pass

    def _atualizar_barra_aut(self):
        ativas = [a for a in self._autorizacoes.values() if not a.encerrada]
        if not ativas:
            self.lbl_aut.configure(text="Autorização: nenhuma ativa  •  clique em Anexar "
                                        "para solicitar (1 hora de uso)",
                                   text_color=common.COR_TEXTO_FRACO)
            self.barra_aut.configure(fg_color=common.COR_PAINEL)
            return
        a = min(ativas, key=lambda x: x.segundos_restantes())
        rest = a.segundos_restantes()
        rotulo = a.nome or a.descricao or a.busid
        mais = f"  (+{len(ativas) - 1} outro(s))" if len(ativas) > 1 else ""
        if rest <= AVISO_EXPIRACAO_S:
            self.lbl_aut.configure(
                text=f"⚠  {rotulo}: a autorização expira em {ss.formatar_tempo(rest)} "
                     f"(às {a.hora_expiracao()}). Conclua as assinaturas.{mais}",
                text_color="#1a1206")
            self.barra_aut.configure(fg_color=common.COR_AVISO)
        else:
            self.lbl_aut.configure(
                text=f"Autorização ativa  •  {rotulo}  •  restam "
                     f"{ss.formatar_tempo(rest)} (até {a.hora_expiracao()}){mais}",
                text_color=common.COR_SUCESSO)
            self.barra_aut.configure(fg_color=common.COR_PAINEL)

    def _encerrar_por_expiracao(self, a, motivo="expirada", tentativa=1):
        """Prazo acabou (ou a API revogou): desanexa com a rotina existente."""
        a.encerrada = True
        self._autorizacoes.pop(a.chave, None)
        self._salvar_autorizacoes()
        rotulo = a.nome or a.descricao or a.busid
        if tentativa == 1:
            txt = ("Autorizacao expirada" if motivo == "expirada"
                   else f"Autorizacao encerrada pela API ({motivo})")
            self.log(f"{txt}: {rotulo}. Desanexando...", "aviso")
            self._notificar(f"{txt}: {rotulo}. O token sera desanexado.")
        disp = common.get_lista(common.carregar_config(), "dispositivos")
        if a.busid in disp:
            disp.remove(a.busid)
            common.salvar_config({"dispositivos": ",".join(disp)})
        g = self._geracao

        def _t():
            porta = None
            for x in eng.listar_anexados():
                if x.get("busid") == a.busid and x.get("servidor") in (a.servidor, ""):
                    porta = x.get("porta")
                    break
            if porta is None:
                ok, msg = True, "nao estava mais anexado nesta estacao"
            else:
                ok, msg = eng.desanexar(porta)
            if ok or tentativa >= TENTATIVAS_DESANEXAR:
                self._evento(api.EV_EXPIRACAO,
                             ("DESANEXADO" if ok else "FALHA_DESANEXAR")
                             if motivo == "expirada" else ("REVOGADO" if ok else
                                                           "FALHA_DESANEXAR"),
                             a.dispositivo(), detalhe=f"{motivo}. {msg or ''}".strip(),
                             aut_id=a.autorizacao_id)
            self.after(0, lambda: self._fim_expiracao(a, ok, msg, motivo, tentativa, g))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_expiracao(self, a, ok, msg, motivo, tentativa, g):
        if g != self._geracao:
            return
        rotulo = a.nome or a.descricao or a.busid
        if ok:
            self.log(f"{rotulo} desanexado (fim da autorizacao).", "ok")
        elif tentativa < TENTATIVAS_DESANEXAR:
            self.log(f"Nao consegui desanexar {rotulo} ({msg}). "
                     f"Nova tentativa em 1 minuto.", "erro")
            self.after(60000, lambda: self._encerrar_por_expiracao(
                a, motivo, tentativa + 1) if g == self._geracao else None)
        else:
            self.log(f"Falha definitiva ao desanexar {rotulo}: {msg}. "
                     f"Desanexe manualmente.", "erro")
            self._notificar(f"Nao foi possivel desanexar {rotulo}. Desanexe manualmente.")
        self.atualizar_anexados()

    # ---- consulta central (API) das autorizacoes vigentes ---------------
    def _iniciar_consulta_autorizacoes(self):
        if not self._consulta_api_ok or not self.sessao:
            return
        auts = [a for a in self._autorizacoes.values()
                if not a.encerrada and a.autorizacao_id]
        if not auts:
            return
        s, g = self.sessao, self._geracao

        def _t():
            resultados = []
            for a in auts:
                try:
                    r = api.consultar_autorizacao(s, a.autorizacao_id)
                except api.ErroApi as e:
                    if e.nao_autorizado:
                        self.after(0, self._sessao_expirada)
                    return  # sem conexao: mantem o prazo local
                if r is None:
                    self._consulta_api_ok = False  # API nao oferece a consulta
                    return
                resultados.append((a, r))
            self.after(0, lambda: self._fim_consulta_autorizacoes(resultados, g))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_consulta_autorizacoes(self, resultados, g):
        if g != self._geracao:
            return
        for a, r in resultados:
            if a.encerrada:
                continue
            if r.get("ativa") is False:
                self._encerrar_por_expiracao(a, motivo=(r.get("motivo") or "revogada")
                                             .lower())
            else:
                a.ajustar(r.get("segundos"))  # so encurta; nunca renova
        self._salvar_autorizacoes()

    # ---- eventos guardados offline ---------------------------------------
    def _iniciar_reenvio_pendentes(self):
        s = self.sessao

        def _t():
            try:
                n = api.reenviar_pendentes(s)
                if n:
                    self.after(0, lambda: self.log(
                        f"{n} registro(s) de auditoria pendente(s) enviado(s) a API.", "info"))
            except Exception:
                pass
        threading.Thread(target=_t, daemon=True).start()

    def _ciclo_pendentes(self, g):
        if g != self._geracao:
            return
        self._iniciar_reenvio_pendentes()
        self.after(INTERVALO_PENDENTES_MS, lambda: self._ciclo_pendentes(g))

    # ---- sair da conta / sessao expirada ---------------------------------
    def sair_da_conta(self):
        ativas = [a for a in self._autorizacoes.values() if not a.encerrada]
        if ativas:
            nomes = ", ".join(a.nome or a.descricao or a.busid for a in ativas)
            if not messagebox.askyesno(
                    common.APP_NAME,
                    f"Ao sair da conta, os dispositivos autorizados para você serão "
                    f"desanexados:\n\n{nomes}\n\nDeseja sair?"):
                return
        self._logout("LOGOUT")

    def trocar_usuario(self):
        """Encerra a sessao e remove as credenciais DPAPI para exibir login vazio."""
        if messagebox.askyesno(common.APP_NAME,
                               "Trocar de usuário encerra a sessão atual e remove "
                               "a senha salva neste computador. Continuar?"):
            self._logout("TROCA_USUARIO", "Entre com o novo usuário.")

    def _sessao_expirada(self):
        if self._saindo or not self.sessao:
            return
        self.log("Sessao expirada ou invalida na API. Entre novamente.", "erro")
        self._logout("SESSAO_EXPIRADA", "Sua sessão expirou. Entre novamente.")

    def _logout(self, motivo, mensagem=""):
        if self._saindo:
            return
        self._saindo = True
        s = self.sessao
        auts = [a for a in self._autorizacoes.values() if not a.encerrada]
        self.log(f"Saindo da conta ({motivo.lower()})...", "info")

        # para todos os ciclos e desmonta a interface principal
        self._geracao += 1
        self._ui_pronta = False
        self.sessao = None
        self._autorizacoes = {}
        ss.apagar_sessao()
        for w in self.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        if bandeja.DISPONIVEL:
            self.protocol("WM_DELETE_WINDOW", self.esconder_janela)
        self._mostrar_login(mensagem or "Você saiu da conta.")
        self.mostrar_janela()

        def _t():
            anex = eng.listar_anexados() if auts else []
            disp_cfg = common.get_lista(common.carregar_config(), "dispositivos")
            restantes = []
            for a in auts:
                porta = next((x["porta"] for x in anex if x.get("busid") == a.busid
                              and x.get("servidor") in (a.servidor, "")), None)
                if porta is None:
                    ok, msg = True, "nao estava anexado"
                else:
                    ok, msg = eng.desanexar(porta)
                if ok and a.busid in disp_cfg:
                    disp_cfg.remove(a.busid)
                if not ok:
                    restantes.append(a)
                ev = api.montar_evento(api.EV_DESANEXADO, "SUCESSO" if ok else "FALHA", s,
                                       a.dispositivo(), f"{motivo.lower()}. {msg or ''}"
                                       .strip(), a.autorizacao_id)
                try:
                    api.enviar_evento(s, ev)
                except Exception:
                    pass
            common.salvar_config({"dispositivos": ",".join(disp_cfg)})
            # o que nao conseguiu desanexar continua com o prazo gravado (expira no proximo login)
            ss.salvar_autorizacoes(restantes)
            ev = api.montar_evento(api.EV_LOGOUT, "SUCESSO", s, detalhe=motivo.lower())
            try:
                api.enviar_evento(s, ev)
            except Exception:
                pass
            if s:
                api.logout(s.token)
            common.registrar_log("ESTACAO", f"[AUDITORIA] {api.EV_LOGOUT} {motivo} "
                                            f"usuario={s.usuario.get('login') if s else ''}")
            self.after(0, lambda: setattr(self, "_saindo", False))
        threading.Thread(target=_t, daemon=True).start()

    # ---- barra de status (rodape) -----------------------------------------
    def _atualizar_status(self, g=None):
        g = self._geracao if g is None else g
        if g != self._geracao:
            return
        try:
            cli = "ok ✓" if eng.cliente_instalado() else "NAO instalado ✗"
            srv = self.entry_servidor.get().strip() or "(nenhum)"
            info = self._info.get(srv)
            if info and info.get("versao"):
                srv += f" (v{info['versao']})"
            usr = self.sessao.nome if self.sessao else "-"
            self.lbl_status.configure(
                text=f"•  Estação  •  Usuário: {usr}  •  Cliente: {cli}  "
                     f"•  Servidor: {srv}  •  Anexados: {self._n_anexados}")
        except Exception:
            pass
        self.after(4000, lambda: self._atualizar_status(g))


if __name__ == "__main__":
    AppEstacao().mainloop()

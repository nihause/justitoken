# -*- coding: utf-8 -*-
"""
usb_servidor.py - SERVIDOR (USB/IP).

Roda no PC onde o dispositivo USB esta plugado.
Compartilha QUALQUER USB (pendrive, HD, token, impressora...) pela rede,
usando o motor usbipd-win. A Estacao anexa o dispositivo e ele passa a
funcionar como se estivesse plugado nela.

Visual moderno com CustomTkinter.
"""

import os
import sys
import json
import socket
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


class AppServidor(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"JustiToken v{common.VERSAO}  -  SERVIDOR")
        try:
            common.aplicar_icone(self, "justitoken-servidor")
        except Exception:
            pass
        self.geometry("720x720")
        self.minsize(660, 620)
        self.configure(fg_color=common.COR_FUNDO)

        self.linhas = {}  # busid -> widgets
        self._ip = common.ip_local()
        self._n_compartilhados = 0
        self._montar_ui()
        self.after(300, self.verificar_motor)
        self.after(4000, lambda: atualizador.verificar_em_segundo_plano(self, self.log))
        self.after(500, self._iniciar_controle)
        self.after(60000, self._atualizar_periodico)
        self._configurar_bandeja()

    # ---- bandeja (icone perto do relogio) --------------------------------
    def _configurar_bandeja(self):
        self.bandeja = bandeja.Bandeja(
            self, "JustiToken - Servidor", cor=common.COR_SUCESSO, tipo="servidor")
        if bandeja.DISPONIVEL:
            self.bandeja.iniciar()
            self.protocol("WM_DELETE_WINDOW", self.esconder_janela)
            self.withdraw()  # inicia minimizado na bandeja
        else:
            self.protocol("WM_DELETE_WINDOW", self.encerrar)

    def mostrar_janela(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.atualizar_lista()

    def esconder_janela(self):
        self.withdraw()

    def encerrar(self):
        try:
            self.bandeja.parar()
        except Exception:
            pass
        self.destroy()

    # ---- UI ---------------------------------------------------------------
    def _montar_ui(self):
        # Rodape primeiro, para ficar sempre visivel no fundo
        self.lbl_status = common.criar_rodape(self, nome_app="JustiToken")
        self.after(800, self._atualizar_status)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=24, pady=(16, 8))
        cabecalho_produto = ctk.CTkFrame(topo, fg_color=common.COR_PAINEL,
                                         corner_radius=14)
        cabecalho_produto.pack(fill="x")
        ctk.CTkLabel(cabecalho_produto, text="🖧  JustiToken  •  Servidor",
                     font=(common.FONTE, 26, "bold"),
                     text_color=common.COR_TEXTO).pack(anchor="w", padx=18, pady=(12, 0))
        ctk.CTkLabel(cabecalho_produto,
                     text="Compartilhe os tokens / dispositivos USB deste PC com as estacoes.",
                     font=(common.FONTE, 13),
                     text_color=common.COR_TEXTO_FRACO).pack(anchor="w", padx=18,
                                                              pady=(2, 12))

        # Banner de instalacao do motor (aparece so se faltar)
        self.banner = ctk.CTkFrame(self, fg_color="#3a2a12", corner_radius=12)
        self.lbl_banner = ctk.CTkLabel(
            self.banner, text="Verificando motor usbipd-win...",
            font=(common.FONTE, 13),
            text_color=common.COR_AVISO, justify="left")
        self.lbl_banner.pack(side="left", padx=16, pady=12)
        self.btn_banner = ctk.CTkButton(
            self.banner, text="Instalar motor", width=150,
            fg_color=common.COR_AVISO, hover_color="#d97706",
            text_color="#1a1206", font=(common.FONTE, 13, "bold"),
            command=self.instalar_motor)
        self.btn_banner.pack(side="right", padx=12, pady=10)
        # fixa a faixa no topo desde ja (sera escondida se o motor existir)
        self.banner.pack(fill="x", padx=24, pady=(4, 6))

        # Cartao endereco
        self.info = ctk.CTkFrame(self, fg_color=common.COR_PAINEL, corner_radius=16)
        info = self.info
        info.pack(fill="x", padx=24, pady=10)
        self.lbl_endereco = ctk.CTkLabel(
            info, justify="left", font=(common.FONTE, 14),
            text_color=common.COR_TEXTO,
            text=(f"Endereco deste servidor:\n"
                  f"   IP: {self._ip}     Porta: {eng.PORTA_USBIP}\n"
                  f"Use esse IP na Estacao para anexar os dispositivos."))
        self.lbl_endereco.pack(anchor="w", padx=20, pady=14, side="left")
        ctk.CTkButton(info, text="🛡  Liberar Firewall", width=160,
                      fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
                      font=(common.FONTE, 13),
                      command=self.liberar_firewall).pack(side="right", padx=16)

        # Opcoes: auto-compartilhar + iniciar com o Windows
        cfg = common.carregar_config()
        op = ctk.CTkFrame(self, fg_color="transparent")
        op.pack(fill="x", padx=26, pady=(2, 0))
        self.var_auto = ctk.BooleanVar(value=bool(cfg.get("auto_compartilhar", False)))
        ctk.CTkSwitch(op, text="Compartilhar automaticamente ao iniciar",
                      variable=self.var_auto, font=(common.FONTE, 13),
                      progress_color=common.COR_SUCESSO,
                      command=self._salvar_auto).pack(side="left")
        ctk.CTkButton(op, text=common.TXT_INICIAR_SISTEMA, width=250,
                      font=(common.FONTE, 12),
                      fg_color=common.COR_PAINEL, hover_color=common.COR_DESTAQUE2,
                      command=self.configurar_inicio).pack(side="right")

        # Barra de acoes da lista
        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=24, pady=(8, 2))
        ctk.CTkLabel(barra, text="Dispositivos USB conectados a este PC",
                     font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO).pack(side="left")
        ctk.CTkButton(barra, text="↻ Atualizar", width=120,
                      fg_color=common.COR_FUNDO, hover_color=common.COR_DESTAQUE2,
                      font=(common.FONTE, 13),
                      command=self.atualizar_lista).pack(side="right")

        # Lista rolavel de dispositivos
        self.lista = ctk.CTkScrollableFrame(self, fg_color=common.COR_PAINEL,
                                            corner_radius=16)
        self.lista.pack(fill="both", expand=True, padx=24, pady=(6, 8))

        # Log
        self.caixa_log = ctk.CTkTextbox(self, height=110, font=(common.FONTE_MONO, 12),
                                        fg_color="#0b0f18",
                                        text_color=common.COR_TEXTO_FRACO,
                                        corner_radius=12)
        self.caixa_log.pack(fill="x", padx=24, pady=(0, 12))
        self.caixa_log.configure(state="disabled")

    # ---- logica -----------------------------------------------------------
    def _salvar_auto(self):
        common.salvar_config({"auto_compartilhar": self.var_auto.get()})
        self.log(f"Auto-compartilhar {'ligado' if self.var_auto.get() else 'desligado'}.",
                 "info")

    def configurar_inicio(self):
        alvo = sys.executable if getattr(sys, "frozen", False) \
            else os.path.abspath(__file__)
        self.var_auto.set(True)
        common.salvar_config({"auto_compartilhar": True})
        self.log(common.TXT_CONFIG_INICIO, "info")

        def _t():
            ok = eng.criar_tarefa_inicio("USBRede_Servidor", alvo)
            self.after(0, lambda: self.log(
                "Pronto! Vai abrir e compartilhar sozinho no logon (sem UAC)." if ok
                else "Falha ao criar a tarefa de inicio.",
                "ok" if ok else "erro"))
        threading.Thread(target=_t, daemon=True).start()

    def auto_compartilhar_inicio(self):
        busids = common.get_lista(common.carregar_config(), "compartilhados")
        if not busids:
            return
        self.log(f"Auto-compartilhar: {len(busids)} dispositivo(s) salvo(s)...", "info")

        def _t():
            for b in busids:
                eng.compartilhar(b)
            self.after(0, self.atualizar_lista)
        threading.Thread(target=_t, daemon=True).start()

    def verificar_motor(self):
        if eng.servidor_instalado():
            self.banner.pack_forget()
            self.log(f"{common.APP_NAME} v{common.VERSAO} - motor {common.MOTOR_SERVIDOR} pronto "
                     f"({eng.servidor_versao() or 'ok'}).", "ok")
            self.atualizar_lista()
            if self.var_auto.get():
                self.auto_compartilhar_inicio()
        else:
            self.lbl_banner.configure(
                text=f"Motor '{common.MOTOR_SERVIDOR}' nao instalado.\n"
                     "Ele e necessario para compartilhar os dispositivos.")
            self.banner.pack(fill="x", padx=24, pady=(4, 6), before=self.info)
            self.log("Motor nao instalado. Clique em 'Instalar motor'.", "aviso")

    def instalar_motor(self):
        self.btn_banner.configure(text="Instalando...", state="disabled")
        self.log(common.TXT_INSTALANDO_SERVIDOR, "info")

        def _t():
            ok, msg = eng.instalar_servidor()
            self.after(0, lambda: self._fim_install(ok, msg))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_install(self, ok, msg):
        self.btn_banner.configure(text="Instalar motor", state="normal")
        self.log(msg, "ok" if ok else "erro")
        if ok:
            self.verificar_motor()
        else:
            messagebox.showerror(common.APP_NAME, msg)

    def liberar_firewall(self):
        self.log("Criando regra de firewall para as portas 3240 e 3241 (admin)...", "info")
        threading.Thread(target=eng.garantir_firewall_servidor, daemon=True).start()

    def _atualizar_periodico(self):
        """A cada 60s atualiza a lista (quem esta usando cada token)."""
        try:
            if self.winfo_viewable():
                self.atualizar_lista()
        except Exception:
            pass
        self.after(60000, self._atualizar_periodico)

    def atualizar_lista(self):
        if not eng.servidor_instalado():
            return
        for w in self.lista.winfo_children():
            w.destroy()
        self.linhas.clear()

        disp = eng.listar_dispositivos_servidor()
        self._n_compartilhados = sum(1 for d in disp if d["compartilhado"])
        if not disp:
            ctk.CTkLabel(self.lista, text="Nenhum dispositivo USB encontrado.",
                         font=(common.FONTE, 13),
                         text_color=common.COR_TEXTO_FRACO).pack(pady=20)
            return

        nomes = common.carregar_nomes()
        for d in disp:
            self._linha_dispositivo(d, nomes.get(d["chave"], ""))

    def _linha_dispositivo(self, d, nome=""):
        cartao = ctk.CTkFrame(self.lista, fg_color=common.COR_FUNDO, corner_radius=12)
        cartao.pack(fill="x", padx=8, pady=6)

        if d["compartilhado"]:
            estado_txt, cor = "● compartilhado", common.COR_SUCESSO
            if d["em_uso"]:
                estado_txt += f"  •  em uso por {d['cliente']}"
                cor = common.COR_AVISO
            else:
                estado_txt += "  •  livre"
            btn_txt, btn_cor, btn_hov = "Parar", common.COR_ERRO, "#dc2626"
            acao = lambda b=d["busid"]: self._toggle(b, ligar=False)
        else:
            estado_txt, cor = "○ privado", common.COR_TEXTO_FRACO
            btn_txt, btn_cor, btn_hov = "Compartilhar", common.COR_SUCESSO, "#16a34a"
            acao = lambda b=d["busid"]: self._toggle(b, ligar=True)

        # botoes primeiro (lado direito), para nunca serem espremidos pelo texto
        ctk.CTkButton(cartao, text=btn_txt, width=120, height=36,
                      font=(common.FONTE, 13, "bold"),
                      fg_color=btn_cor, hover_color=btn_hov,
                      command=acao).pack(side="right", padx=(0, 14), pady=10)
        if d["em_uso"]:
            ctk.CTkButton(cartao, text="Liberar uso", width=100, height=36,
                          font=(common.FONTE, 13, "bold"),
                          fg_color=common.COR_AVISO, hover_color="#d97706",
                          text_color="#1a1206",
                          command=lambda b=d["busid"]: self._forcar_liberar(b)
                          ).pack(side="right", padx=(0, 8), pady=10)
        ctk.CTkButton(cartao, text="✎ Nome", width=80, height=36,
                      font=(common.FONTE, 13),
                      fg_color=common.COR_PAINEL, hover_color=common.COR_DESTAQUE2,
                      command=lambda: self._renomear(d, nome)
                      ).pack(side="right", padx=(0, 8), pady=10)

        esq = ctk.CTkFrame(cartao, fg_color="transparent")
        esq.pack(side="left", fill="x", expand=True, padx=14, pady=8)
        ctk.CTkLabel(esq, text=nome or d["descricao"], font=(common.FONTE, 14, "bold"),
                     text_color=common.COR_TEXTO, anchor="w").pack(anchor="w")
        sub = f"BUSID {d['busid']}"
        if nome:
            sub += f"  •  {d['descricao']}"
        elif d["vidpid"]:
            sub += f"  •  {d['vidpid']}"
        ctk.CTkLabel(esq, text=sub, font=(common.FONTE, 11),
                     text_color=common.COR_TEXTO_FRACO, anchor="w").pack(anchor="w")
        ctk.CTkLabel(esq, text=estado_txt, font=(common.FONTE, 11, "bold"),
                     text_color=cor, anchor="w").pack(anchor="w")

    def _renomear(self, d, nome_atual=""):
        atual = f"\nNome atual: {nome_atual}" if nome_atual else ""
        dialogo = ctk.CTkInputDialog(
            title=f"{common.APP_NAME} - nome do dispositivo",
            text=f"Nome para {d['descricao']} (BUSID {d['busid']})"
                 f"{atual}\n\nEx.: Token Rodrigo. Deixe vazio para remover o nome.")
        novo = dialogo.get_input()
        if novo is None:  # cancelou
            return
        novo = novo.strip()
        if common.salvar_nome(d["chave"], novo):
            self.log(f"{d['busid']}: nome {'definido como ' + repr(novo) if novo else 'removido'}.",
                     "ok")
        else:
            self.log(f"Falha ao salvar o nome de {d['busid']}.", "erro")
        self.atualizar_lista()

    def _toggle(self, busid, ligar):
        acao_txt = "Compartilhando" if ligar else "Parando"
        self.log(f"{acao_txt} {busid} (vai pedir admin)...", "info")

        def _t():
            if ligar:
                ok, _ = eng.compartilhar(busid)
            else:
                ok, _ = eng.descompartilhar(busid)
            self.after(0, lambda: self._fim_toggle(ok, busid, ligar))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_toggle(self, ok, busid, ligar):
        if ok:
            # mantem a lista salva no ini para auto-compartilhar no proximo inicio
            salvos = common.get_lista(common.carregar_config(), "compartilhados")
            if ligar and busid not in salvos:
                salvos.append(busid)
            elif not ligar and busid in salvos:
                salvos.remove(busid)
            common.salvar_config({"compartilhados": ",".join(salvos)})
            self.log(f"{busid} {'compartilhado' if ligar else 'parado'}.", "ok")
        else:
            self.log(f"Falha na operacao com {busid}.", "erro")
        self.atualizar_lista()

    def _forcar_liberar(self, busid):
        self.log(f"Liberando uso de {busid} (vai pedir admin)...", "info")

        def _t():
            ok, msg = eng.forcar_liberar(busid)
            self.after(0, lambda: self._fim_forcar_liberar(ok, busid, msg))
        threading.Thread(target=_t, daemon=True).start()

    def _fim_forcar_liberar(self, ok, busid, msg=""):
        if ok:
            self.log(f"{busid} livre para outra estacao anexar.", "ok")
        else:
            detalhe = f" ({msg})" if msg else ""
            self.log(f"Falha ao liberar {busid}.{detalhe}", "erro")
        self.atualizar_lista()

    # ---- canal de controle (Estacao pede para liberar/forcar) -------------
    def _iniciar_controle(self):
        """Sobe um servidor TCP simples na porta 3241 que atende as estacoes:
        'INFO' (versao, nomes e quem usa cada dispositivo) e 'FORCAR <busid>'."""
        def _serv():
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("0.0.0.0", eng.PORTA_CONTROLE))
                srv.listen(5)
            except Exception as e:
                self.after(0, lambda: self.log(
                    f"Canal de controle (porta {eng.PORTA_CONTROLE}) indisponivel: {e}",
                    "aviso"))
                return
            self.after(0, lambda: self.log(
                f"Canal de controle ativo na porta {eng.PORTA_CONTROLE} "
                f"(permite Forcar a partir das estacoes).", "ok"))
            self._controle_ok = True
            while True:
                try:
                    conn, addr = srv.accept()
                except Exception:
                    break
                threading.Thread(target=self._tratar_controle,
                                 args=(conn, addr), daemon=True).start()
        threading.Thread(target=_serv, daemon=True).start()

    def _info_json(self, ip_estacao):
        nomes = common.carregar_nomes()
        dispositivos = []
        for d in eng.listar_dispositivos_servidor():
            if not d["compartilhado"]:
                continue
            cliente = d["cliente"]
            if d["em_uso"] and not cliente and "clientes" in d:
                # Linux: o usbip nao diz qual busid esta com qual IP. Se a
                # estacao que perguntou tem conexao aberta, considera dela;
                # se nao deu para listar as conexoes, nao acusa perda.
                lista = d["clientes"]
                cliente = ip_estacao if (lista is None or ip_estacao in lista) else ""
            dispositivos.append({
                "busid": d["busid"],
                "nome": nomes.get(d["chave"], ""),
                "descricao": d["descricao"],
                "em_uso": d["em_uso"],
                "cliente": cliente,
            })
        return json.dumps({"app": common.APP_NAME, "versao": common.VERSAO,
                           "voce": ip_estacao, "dispositivos": dispositivos},
                          ensure_ascii=False)

    def _tratar_controle(self, conn, addr):
        try:
            conn.settimeout(150)
            dados = conn.recv(256).decode("utf-8", "replace").strip()
            partes = dados.split()
            if len(partes) == 1 and partes[0].upper() == "INFO":
                conn.sendall((self._info_json(addr[0]) + "\n").encode("utf-8"))
            elif len(partes) == 2 and partes[0].upper() == "FORCAR":
                busid = partes[1]
                self.after(0, lambda: self.log(
                    f"{addr[0]} pediu para FORCAR a liberacao de {busid}...", "info"))
                ok, msg = eng.forcar_liberar(busid)
                conn.sendall(b"OK\n" if ok else (f"ERRO {msg}\n".encode("utf-8")))
                self.after(0, lambda: (self.log(
                    f"{busid} liberado a pedido de {addr[0]}."
                    if ok else f"Falha ao liberar {busid}: {msg}",
                    "ok" if ok else "erro"), self.atualizar_lista()))
            else:
                conn.sendall(b"ERRO comando invalido\n")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def log(self, msg, nivel="info"):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        prefixo = {"ok": "[OK] ", "erro": "[ERRO] ",
                   "aviso": "[!] ", "info": ""}.get(nivel, "")
        self.caixa_log.configure(state="normal")
        self.caixa_log.insert("end", f"{hora}  {prefixo}{msg}\n")
        self.caixa_log.see("end")
        self.caixa_log.configure(state="disabled")
        common.registrar_log("SERVIDOR", f"{prefixo}{msg}")

    # ---- barra de status (rodape) -----------------------------------------
    def _atualizar_status(self):
        try:
            motor = "ok ✓" if eng.servidor_instalado() else "NAO instalado ✗"
            ctrl = "ativo ✓" if getattr(self, "_controle_ok", False) else "iniciando..."
            adm = "admin ✓" if eng.eh_admin() else "SEM admin ✗ (vai pedir UAC)"
            self.lbl_status.configure(
                text=f"•  Servidor  •  Motor: {motor}  •  IP: {self._ip}  "
                     f"•  Controle: {ctrl}  •  {adm}  "
                     f"•  Compartilhados: {self._n_compartilhados}")
        except Exception:
            pass
        self.after(5000, self._atualizar_status)


if __name__ == "__main__":
    AppServidor().mainloop()

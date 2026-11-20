# -*- coding: utf-8 -*-
"""
bandeja.py - Icone na bandeja do sistema (ao lado do relogio).

Permite que o Servidor e a Estacao rodem minimizados perto do relogio,
com menu de "Abrir" e "Sair". Se as bibliotecas nao existirem, o app
continua funcionando normalmente como janela comum.
"""

import threading
import webbrowser

import common

try:
    import pystray
    from PIL import Image, ImageDraw
    DISPONIVEL = True
except Exception:
    DISPONIVEL = False


def _criar_imagem(cor="#3b82f6", tipo="estacao"):
    """Carrega o icone do papel do app; mantem um desenho simples como reserva."""
    try:
        arquivo = "justitoken-servidor.ico" if tipo == "servidor" else "justitoken-estacao.ico"
        with Image.open(common.caminho_recurso("assets", "icones", arquivo)) as icone:
            return icone.convert("RGBA").resize((64, 64))
    except Exception:
        pass

    # Reserva para execucao sem os arquivos de recursos.
    fundo = "#0f1420"
    img = Image.new("RGB", (64, 64), fundo)
    d = ImageDraw.Draw(img)
    # haste
    d.rectangle([29, 14, 35, 46], fill=cor)
    # ponta (conector)
    d.rectangle([26, 8, 38, 16], fill=cor)
    # base circular
    d.ellipse([24, 42, 40, 58], fill=cor)
    # bracos do "tridente" USB
    d.line([32, 30, 20, 36], fill=cor, width=3)
    d.ellipse([16, 32, 22, 38], fill=cor)
    d.line([32, 26, 44, 32], fill=cor, width=3)
    d.rectangle([41, 28, 47, 34], fill=cor)
    return img


class Bandeja:
    """Gerencia o icone na bandeja para uma janela CTk."""

    def __init__(self, app, titulo, cor="#3b82f6", tipo="estacao"):
        self.app = app
        self.titulo = titulo
        self.icone = None
        if not DISPONIVEL:
            return
        imagem = _criar_imagem(cor, tipo)
        menu = pystray.Menu(
            pystray.MenuItem("Abrir", self._abrir, default=True),
            pystray.MenuItem(f"Versão {common.VERSAO}", lambda *_: None, enabled=False),
            pystray.MenuItem("JustiSoft - downloads gratuitos",
                             lambda *_: webbrowser.open(common.URL_DOWNLOADS)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._sair),
        )
        self.icone = pystray.Icon(f"justitoken-{tipo}", imagem, titulo, menu)

    def iniciar(self):
        if self.icone:
            threading.Thread(target=self.icone.run, daemon=True).start()

    def parar(self):
        if self.icone:
            try:
                self.icone.stop()
            except Exception:
                pass

    def _abrir(self, icon=None, item=None):
        self.app.after(0, self.app.mostrar_janela)

    def _sair(self, icon=None, item=None):
        self.parar()
        self.app.after(0, self.app.encerrar)

# -*- coding: utf-8 -*-
"""Gera os icones visuais do JustiToken para Estacao e Servidor."""

from pathlib import Path

from PIL import Image, ImageDraw


TAMANHOS = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "assets" / "icones"


def _escala(valor, tamanho):
    return round(valor * tamanho / 256)


def _xy(coordenadas, tamanho):
    return tuple(_escala(v, tamanho) for v in coordenadas)


def _base(tamanho, cor):
    imagem = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    margem = _escala(12, tamanho)
    desenho.rounded_rectangle(
        [margem, margem, tamanho - margem, tamanho - margem],
        radius=_escala(56, tamanho), fill=cor,
    )
    return imagem, desenho


def icone_estacao(tamanho):
    imagem, d = _base(tamanho, "#2563eb")
    branco, azul_claro = "#f8fafc", "#bfdbfe"
    # Um notebook recebendo o token: deixa claro que e a Estacao de uso.
    d.rounded_rectangle(_xy((55, 72, 172, 153), tamanho), radius=_escala(12, tamanho),
                        outline=branco, width=max(1, _escala(11, tamanho)))
    d.line(_xy((42, 169, 185, 169), tamanho), fill=branco, width=max(1, _escala(12, tamanho)))
    d.rounded_rectangle(_xy((88, 165, 140, 178), tamanho), radius=_escala(5, tamanho), fill=branco)
    # Token USB e seta de entrada no computador.
    d.rounded_rectangle(_xy((171, 102, 212, 150), tamanho), radius=_escala(8, tamanho), fill=azul_claro)
    d.rectangle(_xy((180, 83, 203, 105), tamanho), fill=branco)
    d.rectangle(_xy((184, 79, 190, 88), tamanho), fill=branco)
    d.rectangle(_xy((196, 79, 202, 88), tamanho), fill=branco)
    d.line(_xy((191, 159, 191, 191), tamanho), fill=branco, width=max(1, _escala(10, tamanho)))
    d.polygon([_xy((169, 181), tamanho), _xy((213, 181), tamanho), _xy((191, 207), tamanho)], fill=branco)
    return imagem


def icone_servidor(tamanho):
    imagem, d = _base(tamanho, "#059669")
    branco, verde_claro = "#f8fafc", "#a7f3d0"
    # Rack de servidor com indicadores, ligado a dois clientes da rede.
    d.rounded_rectangle(_xy((55, 60, 167, 177), tamanho), radius=_escala(14, tamanho),
                        outline=branco, width=max(1, _escala(11, tamanho)))
    for y in (91, 124, 157):
        d.line(_xy((76, y, 145, y), tamanho), fill=verde_claro, width=max(1, _escala(8, tamanho)))
        d.ellipse(_xy((66, y - 5, 76, y + 5), tamanho), fill=branco)
    # Rede compartilhada: conexao saindo do rack.
    d.line(_xy((166, 118, 204, 91), tamanho), fill=branco, width=max(1, _escala(9, tamanho)))
    d.line(_xy((166, 131, 204, 164), tamanho), fill=branco, width=max(1, _escala(9, tamanho)))
    d.ellipse(_xy((197, 72, 229, 104), tamanho), fill=branco)
    d.ellipse(_xy((197, 148, 229, 180), tamanho), fill=branco)
    return imagem


def salvar(nome, desenho):
    imagens = [desenho(tamanho) for tamanho, _ in TAMANHOS]
    caminho = DESTINO / f"{nome}.ico"
    imagens[-1].save(caminho, format="ICO", sizes=TAMANHOS)


if __name__ == "__main__":
    DESTINO.mkdir(parents=True, exist_ok=True)
    salvar("justitoken-estacao", icone_estacao)
    salvar("justitoken-servidor", icone_servidor)
    print(f"Ícones gerados em {DESTINO}")

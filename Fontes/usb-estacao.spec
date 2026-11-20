# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
import os
import sys
sys.path.insert(0, SPECPATH)
from versao_exe import arquivo_versao
import re


def versao_estacao(pasta):
    """JustiToken 3.0: gera o recurso de versao com APP_NAME/VERSAO_ESTACAO de
    usb_estacao.py (common.py fica intacto porque e compartilhado com o Servidor)."""
    destino = arquivo_versao(pasta, 'usb-estacao', 'Estacao')
    with open(os.path.join(pasta, 'common.py'), encoding='utf-8') as f:
        com = f.read()
    with open(os.path.join(pasta, 'usb_estacao.py'), encoding='utf-8') as f:
        est = f.read()
    v_ant = re.search(r'^VERSAO\s*=\s*"([^"]+)"', com, re.M).group(1)
    app_ant = re.search(r'^APP_NAME\s*=\s*"([^"]+)"', com, re.M).group(1)
    v_nova = re.search(r'^VERSAO_ESTACAO\s*=\s*"([^"]+)"', est, re.M).group(1)
    app_novo = re.search(r'^APP_NAME\s*=\s*"([^"]+)"', est, re.M).group(1)
    tupla = lambda v: "(%d, %d, %d, %d)" % tuple(([int(x) for x in v.split(".")] + [0] * 4)[:4])
    with open(destino, encoding='utf-8') as f:
        txt = f.read()
    txt = txt.replace(tupla(v_ant), tupla(v_nova)).replace(f"'{v_ant}'", f"'{v_nova}'")
    txt = txt.replace(app_ant, app_novo)
    with open(destino, 'w', encoding='utf-8') as f:
        f.write(txt)
    return destino


datas = []
binaries = []
hiddenimports = []
hiddenimports += collect_submodules('pystray')
hiddenimports += ['api_client', 'sessao', 'tela_login']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [('assets/icones/justitoken-estacao.ico', 'assets/icones')]


a = Analysis(
    ['usb_estacao.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='usb-estacao',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icones/justitoken-estacao.ico',
    version=versao_estacao(SPECPATH),
)

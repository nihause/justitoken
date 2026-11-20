# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
import sys
sys.path.insert(0, SPECPATH)
from versao_exe import arquivo_versao

datas = []
binaries = []
hiddenimports = []
hiddenimports += collect_submodules('pystray')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [('assets/icones/justitoken-servidor.ico', 'assets/icones')]


a = Analysis(
    ['usb_servidor.py'],
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
    name='usb-servidor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    # Sobe sempre elevado: sem isso cada pedido de FORCAR vindo de uma estacao
    # abriria um UAC na tela do servidor, onde nao ha ninguem para confirmar.
    uac_admin=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icones/justitoken-servidor.ico',
    version=arquivo_versao(SPECPATH, 'usb-servidor', 'Servidor'),
)

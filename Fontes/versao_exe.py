# -*- coding: utf-8 -*-
"""
versao_exe.py - Gera o recurso de versao do Windows para os .exe (usado pelos .spec).

A versao vem de common.VERSAO, entao basta mudar la e recompilar: o numero
aparece em Propriedades > Detalhes do usb-servidor.exe / usb-estacao.exe.
"""

import os
import re


def arquivo_versao(pasta, nome_exe, descricao):
    with open(os.path.join(pasta, "common.py"), encoding="utf-8") as f:
        fonte = f.read()
    versao = re.search(r'^VERSAO\s*=\s*"([^"]+)"', fonte, re.M).group(1)
    empresa = re.search(r'^EMPRESA\s*=\s*"([^"]+)"', fonte, re.M).group(1)
    app = re.search(r'^APP_NAME\s*=\s*"([^"]+)"', fonte, re.M).group(1)
    nums = ([int(x) for x in versao.split(".")] + [0, 0, 0, 0])[:4]
    tupla = "(%d, %d, %d, %d)" % tuple(nums)

    texto = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tupla}, prodvers={tupla}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', '{empresa}'),
      StringStruct('FileDescription', '{app} - {descricao}'),
      StringStruct('FileVersion', '{versao}'),
      StringStruct('InternalName', '{nome_exe}'),
      StringStruct('LegalCopyright', '{empresa} - versao 100% gratuita'),
      StringStruct('OriginalFilename', '{nome_exe}.exe'),
      StringStruct('ProductName', '{app}'),
      StringStruct('ProductVersion', '{versao}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
"""
    destino = os.path.join(pasta, "build", f"versao-{nome_exe}.txt")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    return destino

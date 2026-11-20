# -*- coding: utf-8 -*-
"""Testes do backend Linux e do atualizador, sem precisar de Linux nem de internet.
Rode:  python Fontes/tests/test_linux.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import usbip_linux as lx      # noqa: E402
import usbip_engine as eng    # noqa: E402
import atualizador as at      # noqa: E402

LIST_L = """ - busid 1-1 (0781:5567)
   SanDisk Corp. : Cruzer Blade (0781:5567)

 - busid 1-2.3 (096e:0602)
   Feitian Technologies, Inc. : ePass2003 (096e:0602)

"""

LIST_R = """Exportable USB devices
======================
 - 192.168.0.5
        1-1: SanDisk Corp. : Cruzer Blade (0781:5567)
           : /sys/devices/pci0000:00/0000:00:14.0/usb1/1-1
           : (Defined at Interface level) (00/00/00)
        1-2.3: Feitian Technologies, Inc. : ePass2003 (096e:0602)
"""

PORT = """Imported USB devices
====================
Port 00: <Port in Use> at High Speed(480Mbps)
       SanDisk Corp. : Cruzer Blade (0781:5567)
       3-1 -> usbip://192.168.0.5:3240/1-1
           -> remote bus/dev 001/003
"""


class TestParsing(unittest.TestCase):
    def test_lista_local(self):
        with mock.patch.object(lx, "caminho_usbip", return_value="/usr/bin/usbip"), \
             mock.patch.object(lx, "_run", return_value=(0, LIST_L)), \
             mock.patch.object(lx, "_ler", return_value=""), \
             mock.patch("os.path.exists", return_value=False):
            d = lx.listar_dispositivos_servidor()
        self.assertEqual([x["busid"] for x in d], ["1-1", "1-2.3"])
        self.assertEqual(d[1]["vidpid"], "096e:0602")
        self.assertIn("ePass2003", d[1]["descricao"])
        self.assertFalse(d[0]["compartilhado"])

    def test_lista_remota_aceita_busid_com_ponto(self):
        with mock.patch.object(eng, "caminho_cliente", return_value="/usr/bin/usbip"), \
             mock.patch.object(eng, "_run", return_value=(0, LIST_R)):
            d = eng.listar_dispositivos_remotos("192.168.0.5")
        self.assertEqual([x["busid"] for x in d], ["1-1", "1-2.3"])

    def test_port(self):
        with mock.patch.object(eng, "caminho_cliente", return_value="/usr/bin/usbip"), \
             mock.patch.object(eng, "_run", return_value=(0, PORT)):
            a = eng.listar_anexados()
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["porta"], a[0]["servidor"], a[0]["busid"]),
                         ("00", "192.168.0.5", "1-1"))


class TestAtualizador(unittest.TestCase):
    def test_comparacao_de_versoes(self):
        self.assertGreater(at._tupla("3.10.0"), at._tupla("3.9.9"))
        self.assertGreater(at._tupla("3.1.0"), at._tupla("3.0.3"))

    def test_caminhos_permitidos(self):
        ok = at._caminho_permitido
        self.assertTrue(ok("Fontes/usb_estacao.py"))
        self.assertTrue(ok("instalar.sh"))
        self.assertFalse(ok("config.ini"))
        self.assertFalse(ok("Fontes/config.ini") or ok("sessao.dat"))
        self.assertFalse(ok("Fontes/backup_x/usb_estacao.py"))
        self.assertFalse(ok("Fontes/../config.ini"))
        self.assertFalse(ok("/etc/passwd"))

    def test_helper_sh_valido(self):
        # confere que o script privilegiado e sintaxe sh valida e rejeita busid ruim
        import shutil
        import subprocess
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("sh indisponivel")
        helper = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "scripts", "justitoken-priv.sh")
        self.assertEqual(subprocess.run([sh, "-n", helper]).returncode, 0)
        r = subprocess.run([sh, helper, "bind", "1-1; rm -rf /"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("busid invalido", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

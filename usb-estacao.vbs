' Inicia a ESTACAO de USB pela Rede sem janela de console (silencioso).
' Funciona de qualquer pasta: usa o caminho deste proprio arquivo.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
raiz = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = raiz & "\Fontes"
sh.Run "pyw """ & raiz & "\Fontes\usb_estacao.py""", 0, False

# JustiToken · USB pela Rede

Plugue qualquer dispositivo USB (token de certificado, pendrive, impressora, leitor) em um computador **servidor** e use-o em outro, a **estação**, como se estivesse ligado nele. Funciona em **Windows e Linux**, em qualquer combinação (servidor Linux com estação Windows e vice-versa), porque o protocolo é o USB/IP padrão.

| | Servidor (compartilha o USB) | Estação (usa o USB) |
|---|---|---|
| **Windows** | [usbipd-win](https://github.com/dorssel/usbipd-win) | [usbip-win2](https://github.com/vadimgrn/usbip-win2) |
| **Linux** | pacote `usbip` + módulo `usbip-host` | pacote `usbip` + módulo `vhci-hcd` |

A interface (Python + CustomTkinter) é a mesma nos dois sistemas.

## Instalação

**Windows:** rode `instalar.bat` e siga os passos 1 a 3.

**Linux:**

```bash
git clone https://github.com/nihause/justitoken.git
cd justitoken
./instalar.sh        # passo 1 (Python/Tk + bibliotecas), 2 (motor usbip), 4 ou 5 (servidor/estação)
./usb-servidor.sh    # ou ./usb-estacao.sh
```

No Linux, as ações que exigem root (compartilhar, anexar, firewall) passam todas por um único script, `Fontes/scripts/justitoken-priv.sh`, que valida os argumentos. Por padrão o sistema pede a senha pelo `pkexec`. A opção 3 do `instalar.sh` instala esse script em `/usr/local/lib/justitoken/` e libera **só ele** no sudoers, para não pedir senha a cada ação.

## Uso

1. **Servidor:** abra, libere o firewall (1 vez), atualize a lista e clique em *Compartilhar* no dispositivo. Anote o IP.
2. **Estação:** digite o IP do servidor, *Buscar dispositivos*, *Anexar*.
3. Fora da rede local: encaminhe a porta TCP **3240** (e **3241**, canal de controle) no roteador do servidor.

O **modo arquivos** (WebDAV, sem driver) serve só para pendrive/HD. No Windows monta uma letra de unidade; no Linux monta via GVFS (`gio mount`).

## Atualização

O programa verifica o GitHub ao abrir e pergunta se quer atualizar. Também dá para rodar a qualquer momento:

```bash
./atualizar.sh          # Linux
atualizar.bat           # Windows
python Fontes/atualizador.py --verificar   # só consulta (código de saída 10 = há versão nova)
```

- Clone git: faz `git pull --ff-only` e **recusa** se houver alteração local.
- Pasta sem git: baixa o zip e troca só os arquivos do programa, guardando os antigos em `.backup_atualizacao/`. `config.ini`, sessão, autorizações e logs nunca são tocados.
- Desligar a checagem: `verificar_atualizacao = false` no `config.ini` (veja `config.example.ini`).
- Executável empacotado (PyInstaller): não se substitui sozinho; abre a página de *Releases*.

A versão publicada fica no arquivo `VERSION`. Para lançar: altere o `VERSION`, faça commit e push na `main`.

## Limitações conhecidas

- No Linux a sessão "manter conectado" guarda só o token (0600), nunca a senha. No Windows continua protegida pelo DPAPI.
- No Linux o `usbip` não informa qual IP usa qual dispositivo quando há mais de uma estação conectada; o servidor infere pela conexão aberta na porta 3240.
- O backend Linux foi escrito e testado com a saída de exemplo do `usbip`; teste em hardware real antes de depender dele em produção.

## Desenvolvimento

```bash
python Fontes/tests/test_linux.py
```

"""Script utilitário para validar o envio real de e-mail (Gmail/SMTP).

Lê a mesma configuração de ambiente usada pela aplicação, monta o transporte de
e-mail e envia UMA mensagem de teste. Serve para validar rapidamente que a
senha de app do Gmail e as variáveis BUSCA_SMTP_* estão corretas.

NÃO é um teste automatizado: faz uma conexão SMTP real.

Variáveis de ambiente
---------------------
    BUSCA_SMTP_HOST      (default: smtp.gmail.com)
    BUSCA_SMTP_PORT      (default: 587)
    BUSCA_SMTP_USER      (obrigatória) e-mail/login remetente
    BUSCA_SMTP_PASSWORD  (obrigatória) senha de app do Gmail
    BUSCA_SMTP_FROM      (opcional, default = BUSCA_SMTP_USER)
    BUSCA_SMTP_TO        (opcional, default = BUSCA_SMTP_USER) destinatário do teste

Uso (Windows / PowerShell):
    py enviar_email_teste.py

A senha NUNCA é impressa.
"""

from __future__ import annotations

import os
import sys

from notificacoes_ru.notificacao.transporte_email import (
    transporte_email_do_ambiente,
)
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato

ASSUNTO_INFO = "teste de envio do Marimbondos Informes RU"


def main() -> int:
    transporte = transporte_email_do_ambiente()
    if transporte is None:
        print(
            "ERRO: configure BUSCA_SMTP_USER e BUSCA_SMTP_PASSWORD "
            "(senha de app do Gmail) antes de rodar este script.",
            file=sys.stderr,
        )
        return 1

    usuario = os.environ["BUSCA_SMTP_USER"]
    destinatario = os.environ.get("BUSCA_SMTP_TO") or usuario
    host = os.environ.get("BUSCA_SMTP_HOST", "smtp.gmail.com")
    porta = os.environ.get("BUSCA_SMTP_PORT", "587")

    destino = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor=destinatario)
    mensagem = (
        "Olá! Este é um e-mail de teste do Marimbondos Informes RU.\n\n"
        "Se você recebeu esta mensagem, o envio por SMTP (Gmail) está "
        "funcionando corretamente."
    )

    print(f"Enviando e-mail de teste via {host}:{porta} para {destinatario} ...")
    try:
        # timeout generoso para o teste manual.
        transporte(destino, mensagem, timeout=30.0)
    except Exception as erro:  # noqa: BLE001 - reporta qualquer falha de envio
        print(f"FALHA no envio: {type(erro).__name__}: {erro}", file=sys.stderr)
        return 1

    print("SUCESSO: e-mail de teste enviado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

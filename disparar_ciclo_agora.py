"""Dispara o ciclo semanal REAL agora, sob demanda (sem esperar o sábado).

Usa exatamente o mesmo wiring do app de produção (``composicao.compor_aplicacao``):
lê o e-mail e os pratos que você cadastrou pela INTERFACE WEB (no banco
``notificacoes_ru.db``), coleta o cardápio real, detecta os pratos monitorados e
envia as notificações por e-mail (resumo da semana + agenda os lembretes).

Serve para testar o fluxo de ponta a ponta como ele realmente acontece, sem
precisar esperar o horário agendado.

Pré-requisitos:
  1. Credenciais do Gmail no arquivo ``.env`` (BUSCA_SMTP_USER / BUSCA_SMTP_PASSWORD).
  2. Ter cadastrado, na interface (http://127.0.0.1:8000):
       - o seu e-mail em "E-mail de notificação";
       - ao menos um prato em "Pratos monitorados".

Uso:
    py disparar_ciclo_agora.py

A senha NUNCA é impressa.
"""

from __future__ import annotations

import sys

from notificacoes_ru.composicao import CAMINHO_CHAVE_PADRAO, compor_aplicacao, transporte_noop
from notificacoes_ru.notificacao.transporte_email import transporte_email_do_ambiente
from notificacoes_ru.persistencia.esquema import CAMINHO_BANCO_PADRAO


def main() -> int:
    # Carrega credenciais do .env, como o app real faz no __main__.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        pass

    transporte = transporte_email_do_ambiente()
    if transporte is None:
        print(
            "ERRO: credenciais SMTP ausentes. Preencha BUSCA_SMTP_USER e "
            "BUSCA_SMTP_PASSWORD no arquivo .env antes de rodar.",
            file=sys.stderr,
        )
        return 1

    # Monta a aplicação REAL sobre o banco de arquivo (o mesmo que a interface
    # usa), com a chave Fernet persistente e o transporte de e-mail do .env.
    composicao = compor_aplicacao(
        caminho_banco=CAMINHO_BANCO_PADRAO,
        caminho_chave=CAMINHO_CHAVE_PADRAO,
        transporte=transporte,
    )

    config = composicao.contexto.config_repo
    canal, contato = config.canal_e_contato()
    pratos = config.pratos_monitorados()

    # Diagnóstico do que foi cadastrado pela interface.
    if contato is None:
        print(
            "ATENÇÃO: nenhum e-mail cadastrado. Abra http://127.0.0.1:8000 e "
            "preencha 'E-mail de notificação' antes de testar.",
            file=sys.stderr,
        )
        return 1
    if not pratos:
        print(
            "ATENÇÃO: nenhum prato monitorado cadastrado. Abra "
            "http://127.0.0.1:8000 e adicione ao menos um prato.",
            file=sys.stderr,
        )
        return 1

    print(f"E-mail de destino cadastrado: {contato.valor}")
    print("Pratos monitorados:", ", ".join(p.nome_original for p in pratos))
    print("Disparando o ciclo semanal real (coleta -> detecção -> notificação) ...")

    # Executa o MESMO método que roda no sábado às 11h.
    composicao.agendador.executar_ciclo_semanal()

    print(
        "\nCiclo concluído. Se algum prato foi encontrado, um e-mail de resumo "
        f"foi enviado para {contato.valor} e os lembretes diários foram agendados.\n"
        "Verifique a caixa de entrada (e o spam)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

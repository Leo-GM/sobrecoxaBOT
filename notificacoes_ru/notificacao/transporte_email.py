"""Transporte de notificação por e-mail via SMTP (compatível com Gmail).

Este módulo fornece uma implementação concreta do Protocol
:class:`~notificacoes_ru.notificacao.canais.Transporte` que envia a mensagem por
um servidor SMTP usando apenas a biblioteca padrão (``smtplib`` +
``email.message``). É projetado para funcionar com o Gmail:

* ``smtp.gmail.com`` na porta ``587`` com STARTTLS (``usar_tls=True``, padrão); ou
* ``smtp.gmail.com`` na porta ``465`` com SSL (``usar_tls=False`` + porta 465).

Em ambos os casos é necessária uma *senha de app* do Gmail (não a senha normal
da conta), gerada em https://myaccount.google.com/apppasswords.

Contrato do transporte (ver ``canais.Transporte``): a função recebe
``(destino, mensagem, timeout)`` e **lança exceção** em caso de falha. O
adaptador de canal (``_CanalBase.enviar``) converte sucesso/exceção em
``ResultadoEnvio``; portanto este módulo **não** engole erros de SMTP/conexão.

A senha **nunca** é registrada em log (Req 6.5).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from notificacoes_ru.notificacao.canais import Transporte
from notificacoes_ru.nucleo.tipos import Dado_de_Contato

# Assunto padrão das notificações enviadas por e-mail.
ASSUNTO_PADRAO = "Marimbondos Informes RU — Cardápio da semana"

# Defaults compatíveis com o Gmail (STARTTLS na 587).
HOST_PADRAO = "smtp.gmail.com"
PORTA_PADRAO = 587


def _montar_mensagem(
    *,
    remetente: str,
    destinatario: str,
    assunto: str,
    corpo: str,
) -> EmailMessage:
    """Monta um ``EmailMessage`` de texto puro em UTF-8."""
    email = EmailMessage()
    email["From"] = remetente
    email["To"] = destinatario
    email["Subject"] = assunto
    email.set_content(corpo, charset="utf-8")
    return email


def criar_transporte_email(
    *,
    host: str,
    porta: int,
    usuario: str,
    senha: str,
    remetente: str | None = None,
    usar_tls: bool = True,
    assunto_padrao: str = ASSUNTO_PADRAO,
) -> Transporte:
    """Cria um :class:`Transporte` que envia a notificação por SMTP.

    Parâmetros
    ----------
    host, porta:
        Endereço do servidor SMTP. Para Gmail: ``smtp.gmail.com`` com porta
        ``587`` (STARTTLS) ou ``465`` (SSL).
    usuario, senha:
        Credenciais de autenticação SMTP. No Gmail, ``usuario`` é o e-mail e
        ``senha`` é uma *senha de app*. A senha nunca é registrada em log.
    remetente:
        Endereço no cabeçalho ``From``. Quando ``None``, usa ``usuario``.
    usar_tls:
        Quando ``True`` (padrão), conecta em texto e faz ``STARTTLS`` (porta
        587). Quando ``False``, abre uma conexão SSL direta (porta 465).
    assunto_padrao:
        Assunto aplicado a todas as mensagens enviadas por este transporte.

    Retorna
    -------
    Um callable ``(destino, mensagem, timeout) -> None`` compatível com o
    Protocol ``Transporte``: envia o e-mail e, em caso de erro de SMTP ou
    conexão, deixa a exceção propagar (o adaptador de canal a converte em
    ``ResultadoEnvio``).
    """
    de = remetente or usuario

    def _enviar(destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
        email = _montar_mensagem(
            remetente=de,
            destinatario=destino.valor,
            assunto=assunto_padrao,
            corpo=mensagem,
        )

        if usar_tls:
            # STARTTLS: conecta em texto e eleva para TLS antes do login.
            with smtplib.SMTP(host, porta, timeout=timeout) as servidor:
                servidor.starttls()
                servidor.login(usuario, senha)
                servidor.send_message(email)
        else:
            # SSL direto (porta 465).
            with smtplib.SMTP_SSL(host, porta, timeout=timeout) as servidor:
                servidor.login(usuario, senha)
                servidor.send_message(email)

    return _enviar


def transporte_email_do_ambiente() -> Transporte | None:
    """Monta um transporte de e-mail a partir de variáveis de ambiente.

    Lê a configuração SMTP do ambiente e, se as credenciais obrigatórias
    estiverem presentes, devolve um :class:`Transporte` pronto. Caso contrário
    devolve ``None`` — permitindo ao chamador cair no transporte *no-op* quando
    o e-mail não está configurado.

    Variáveis lidas
    ---------------
    ``BUSCA_SMTP_HOST``:
        Host do servidor SMTP. Default: ``smtp.gmail.com``.
    ``BUSCA_SMTP_PORT``:
        Porta do servidor SMTP. Default: ``587``.
    ``BUSCA_SMTP_USER`` (obrigatória):
        E-mail/login do remetente.
    ``BUSCA_SMTP_PASSWORD`` (obrigatória):
        Senha de app do Gmail (ou senha SMTP).
    ``BUSCA_SMTP_FROM``:
        Endereço do cabeçalho ``From``. Default: ``BUSCA_SMTP_USER``.

    Retorna ``None`` se ``BUSCA_SMTP_USER`` ou ``BUSCA_SMTP_PASSWORD`` não
    estiverem definidas. A senha nunca é registrada em log.
    """
    # ``.strip() or None`` trata variável ausente OU vazia da mesma forma. Isso
    # é importante no GitHub Actions: um secret não cadastrado é injetado como
    # string vazia (""), não como ausente — então precisamos cair no default
    # em vez de usar "" (que quebraria o host ou o int(porta)).
    def _env(nome: str) -> str | None:
        valor = os.environ.get(nome)
        return valor.strip() if valor and valor.strip() else None

    usuario = _env("BUSCA_SMTP_USER")
    senha = _env("BUSCA_SMTP_PASSWORD")
    if not usuario or not senha:
        return None

    host = _env("BUSCA_SMTP_HOST") or HOST_PADRAO
    porta = int(_env("BUSCA_SMTP_PORT") or PORTA_PADRAO)
    remetente = _env("BUSCA_SMTP_FROM") or usuario
    # STARTTLS por padrão; porta 465 usa SSL direto.
    usar_tls = porta != 465

    return criar_transporte_email(
        host=host,
        porta=porta,
        usuario=usuario,
        senha=senha,
        remetente=remetente,
        usar_tls=usar_tls,
    )

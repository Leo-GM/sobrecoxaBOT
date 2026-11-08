"""Testes offline do transporte de e-mail (SMTP) — sem rede real.

Exercitam :mod:`notificacoes_ru.notificacao.transporte_email` usando um mock de
``smtplib.SMTP`` / ``smtplib.SMTP_SSL`` (via ``unittest.mock.patch``). Verificam:

* host/porta/timeout corretos passados ao construtor do SMTP;
* ``starttls`` chamado quando ``usar_tls=True`` (e NÃO no modo SSL);
* ``login`` com usuário/senha;
* ``send_message`` chamado com From/To/Subject/corpo corretos;
* exceções de SMTP propagam (o transporte NÃO as engole);
* ``transporte_email_do_ambiente`` lê as variáveis de ambiente e devolve
  ``None`` sem credenciais ou um ``Transporte`` quando USER+PASSWORD existem.

Nenhuma conexão de rede real é feita.
"""

from __future__ import annotations

from email.message import EmailMessage
from unittest import mock

import pytest

from notificacoes_ru.notificacao import transporte_email as te
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato


def _destino(valor: str = "alguem@exemplo.com") -> Dado_de_Contato:
    return Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor=valor)


def _servidor_mock():
    """Cria um mock de servidor SMTP usável como context manager."""
    servidor = mock.MagicMock(name="servidor_smtp")
    # Suporte ao protocolo de context manager (``with smtplib.SMTP(...) as s``).
    servidor.__enter__.return_value = servidor
    servidor.__exit__.return_value = False
    return servidor


# ---------------------------------------------------------------------------
# criar_transporte_email — modo STARTTLS (porta 587)
# ---------------------------------------------------------------------------
def test_starttls_envia_com_host_porta_timeout_e_login():
    servidor = _servidor_mock()

    with mock.patch.object(te.smtplib, "SMTP", return_value=servidor) as smtp_cls:
        transporte = te.criar_transporte_email(
            host="smtp.gmail.com",
            porta=587,
            usuario="remetente@gmail.com",
            senha="segredo-app",
            usar_tls=True,
            assunto_padrao="Assunto X",
        )
        transporte(_destino("dest@exemplo.com"), "corpo da mensagem", timeout=12.5)

    # Construtor do SMTP: host, porta e timeout corretos.
    smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=12.5)

    # STARTTLS chamado antes do login.
    servidor.starttls.assert_called_once_with()
    servidor.login.assert_called_once_with("remetente@gmail.com", "segredo-app")

    # send_message chamado uma vez com a mensagem montada corretamente.
    servidor.send_message.assert_called_once()
    (enviado,), _ = servidor.send_message.call_args
    assert isinstance(enviado, EmailMessage)
    assert enviado["From"] == "remetente@gmail.com"
    assert enviado["To"] == "dest@exemplo.com"
    assert enviado["Subject"] == "Assunto X"
    assert enviado.get_content().strip() == "corpo da mensagem"


def test_remetente_explicito_vira_cabecalho_from():
    servidor = _servidor_mock()

    with mock.patch.object(te.smtplib, "SMTP", return_value=servidor):
        transporte = te.criar_transporte_email(
            host="smtp.gmail.com",
            porta=587,
            usuario="login@gmail.com",
            senha="x",
            remetente="noreply@exemplo.com",
        )
        transporte(_destino(), "oi", timeout=5.0)

    (enviado,), _ = servidor.send_message.call_args
    assert enviado["From"] == "noreply@exemplo.com"
    # O login continua usando o usuário, não o remetente.
    servidor.login.assert_called_once_with("login@gmail.com", "x")


# ---------------------------------------------------------------------------
# criar_transporte_email — modo SSL (porta 465)
# ---------------------------------------------------------------------------
def test_ssl_usa_smtp_ssl_e_nao_chama_starttls():
    servidor = _servidor_mock()

    with mock.patch.object(
        te.smtplib, "SMTP_SSL", return_value=servidor
    ) as ssl_cls, mock.patch.object(te.smtplib, "SMTP") as smtp_cls:
        transporte = te.criar_transporte_email(
            host="smtp.gmail.com",
            porta=465,
            usuario="u@gmail.com",
            senha="s",
            usar_tls=False,
        )
        transporte(_destino(), "corpo", timeout=20.0)

    ssl_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=20.0)
    smtp_cls.assert_not_called()
    servidor.starttls.assert_not_called()
    servidor.login.assert_called_once_with("u@gmail.com", "s")
    servidor.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Propagação de exceção
# ---------------------------------------------------------------------------
def test_excecao_do_smtp_propaga():
    import smtplib

    servidor = _servidor_mock()
    servidor.send_message.side_effect = smtplib.SMTPException("falhou")

    with mock.patch.object(te.smtplib, "SMTP", return_value=servidor):
        transporte = te.criar_transporte_email(
            host="h", porta=587, usuario="u", senha="s"
        )
        with pytest.raises(smtplib.SMTPException):
            transporte(_destino(), "corpo", timeout=5.0)


def test_erro_de_conexao_propaga():
    with mock.patch.object(
        te.smtplib, "SMTP", side_effect=OSError("conexão recusada")
    ):
        transporte = te.criar_transporte_email(
            host="h", porta=587, usuario="u", senha="s"
        )
        with pytest.raises(OSError):
            transporte(_destino(), "corpo", timeout=5.0)


# ---------------------------------------------------------------------------
# transporte_email_do_ambiente
# ---------------------------------------------------------------------------
def test_ambiente_sem_credenciais_retorna_none(monkeypatch):
    for var in (
        "BUSCA_SMTP_USER",
        "BUSCA_SMTP_PASSWORD",
        "BUSCA_SMTP_HOST",
        "BUSCA_SMTP_PORT",
        "BUSCA_SMTP_FROM",
    ):
        monkeypatch.delenv(var, raising=False)

    assert te.transporte_email_do_ambiente() is None


def test_ambiente_so_user_sem_senha_retorna_none(monkeypatch):
    monkeypatch.setenv("BUSCA_SMTP_USER", "u@gmail.com")
    monkeypatch.delenv("BUSCA_SMTP_PASSWORD", raising=False)

    assert te.transporte_email_do_ambiente() is None


def test_ambiente_com_user_e_senha_retorna_transporte(monkeypatch):
    monkeypatch.setenv("BUSCA_SMTP_USER", "u@gmail.com")
    monkeypatch.setenv("BUSCA_SMTP_PASSWORD", "senha-app")
    monkeypatch.delenv("BUSCA_SMTP_HOST", raising=False)
    monkeypatch.delenv("BUSCA_SMTP_PORT", raising=False)
    monkeypatch.delenv("BUSCA_SMTP_FROM", raising=False)

    transporte = te.transporte_email_do_ambiente()
    assert transporte is not None
    assert callable(transporte)

    # Usa os defaults de Gmail (STARTTLS na 587) e as credenciais do ambiente.
    servidor = _servidor_mock()
    with mock.patch.object(te.smtplib, "SMTP", return_value=servidor) as smtp_cls:
        transporte(_destino("d@exemplo.com"), "oi", timeout=9.0)

    smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=9.0)
    servidor.starttls.assert_called_once_with()
    servidor.login.assert_called_once_with("u@gmail.com", "senha-app")
    (enviado,), _ = servidor.send_message.call_args
    assert enviado["From"] == "u@gmail.com"
    assert enviado["To"] == "d@exemplo.com"


def test_ambiente_porta_465_usa_ssl(monkeypatch):
    monkeypatch.setenv("BUSCA_SMTP_USER", "u@gmail.com")
    monkeypatch.setenv("BUSCA_SMTP_PASSWORD", "senha-app")
    monkeypatch.setenv("BUSCA_SMTP_PORT", "465")
    monkeypatch.delenv("BUSCA_SMTP_HOST", raising=False)
    monkeypatch.delenv("BUSCA_SMTP_FROM", raising=False)

    transporte = te.transporte_email_do_ambiente()
    assert transporte is not None

    servidor = _servidor_mock()
    with mock.patch.object(
        te.smtplib, "SMTP_SSL", return_value=servidor
    ) as ssl_cls:
        transporte(_destino(), "oi", timeout=9.0)

    ssl_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=9.0)
    servidor.starttls.assert_not_called()

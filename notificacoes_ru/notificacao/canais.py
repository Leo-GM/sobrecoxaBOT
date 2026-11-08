"""Adaptadores de canal (``CanalNotificacao``).

Implementa um adaptador por ``Canal_de_Notificacao`` suportado — WhatsApp,
Telegram e e-mail — conforme a seção *Components and Interfaces* do design::

    interface CanalNotificacao:
        enviar(destino: Dado_de_Contato, mensagem: str) -> ResultadoEnvio  # timeout 30s

Cada adaptador:

* valida o formato do contato recebido (Req 4.8) antes de tentar enviar;
* confere que o canal do contato corresponde ao canal do adaptador;
* delega o envio efetivo a uma função de *transporte* injetável, mantendo o
  adaptador testável offline (sem enviar e-mails/mensagens reais). O transporte
  recebe ``(destino, mensagem, timeout)`` e deve lançar exceção em caso de
  erro; o adaptador converte sucesso/exceção/timeout em ``ResultadoEnvio``.

O timeout padrão de envio é de 30 segundos (Req 4.2).
"""

from __future__ import annotations

from typing import Callable, Protocol

from notificacoes_ru.nucleo.resultados import ResultadoEnvio
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato

from notificacoes_ru.notificacao.mensagens import validar_contato

# Timeout padrão de envio por canal (Req 4.2).
TIMEOUT_ENVIO_SEGUNDOS: float = 30.0


class Transporte(Protocol):
    """Camada de envio efetivo de uma mensagem por um canal.

    Deve concluir o envio dentro de ``timeout`` segundos e lançar exceção em
    caso de falha (incluindo estouro de tempo). Implementações reais integram a
    API do WhatsApp/Telegram ou um servidor SMTP; nos testes é substituída por
    um duble determinístico e offline.
    """

    def __call__(
        self,
        destino: Dado_de_Contato,
        mensagem: str,
        timeout: float,
    ) -> None:
        ...


class _CanalBase:
    """Base comum aos adaptadores de canal.

    Concentra a validação de contato, a verificação de canal e a conversão do
    resultado do transporte em ``ResultadoEnvio`` (Req 4.2, 4.5, 4.8).
    """

    canal: Canal_de_Notificacao

    def __init__(
        self,
        transporte: Transporte,
        timeout: float = TIMEOUT_ENVIO_SEGUNDOS,
    ) -> None:
        self._transporte = transporte
        self._timeout = timeout

    def enviar(self, destino: Dado_de_Contato, mensagem: str) -> ResultadoEnvio:
        """Envia ``mensagem`` para ``destino`` (timeout 30s por padrão).

        Retorna ``ResultadoEnvio(sucesso=True)`` quando o transporte conclui
        sem erro; ``ResultadoEnvio(sucesso=False, motivo=...)`` quando o contato
        é inválido, o canal não corresponde ou o transporte falha/estoura o
        tempo (Req 4.5).
        """
        if destino.canal is not self.canal:
            return ResultadoEnvio(
                sucesso=False,
                motivo=(
                    f"canal do contato ({destino.canal.value}) não corresponde "
                    f"ao adaptador ({self.canal.value})"
                ),
            )

        if not validar_contato(destino):
            return ResultadoEnvio(
                sucesso=False,
                motivo=f"contato inválido para o canal {self.canal.value}",
            )

        try:
            self._transporte(destino, mensagem, self._timeout)
        except Exception as erro:  # noqa: BLE001 - qualquer falha de envio
            return ResultadoEnvio(sucesso=False, motivo=str(erro) or type(erro).__name__)

        return ResultadoEnvio(sucesso=True)


class NotificadorWhatsApp(_CanalBase):
    """Adaptador do canal WhatsApp (destino: número de telefone)."""

    canal = Canal_de_Notificacao.WHATSAPP


class NotificadorTelegram(_CanalBase):
    """Adaptador do canal Telegram (destino: @username ou chat id)."""

    canal = Canal_de_Notificacao.TELEGRAM


class NotificadorEmail(_CanalBase):
    """Adaptador do canal e-mail (destino: endereço de e-mail / SMTP)."""

    canal = Canal_de_Notificacao.EMAIL


# Mapeamento de conveniência: canal -> classe de adaptador.
ADAPTADORES: dict[Canal_de_Notificacao, type[_CanalBase]] = {
    Canal_de_Notificacao.WHATSAPP: NotificadorWhatsApp,
    Canal_de_Notificacao.TELEGRAM: NotificadorTelegram,
    Canal_de_Notificacao.EMAIL: NotificadorEmail,
}


def criar_canal(
    canal: Canal_de_Notificacao,
    transporte: Transporte,
    timeout: float = TIMEOUT_ENVIO_SEGUNDOS,
) -> _CanalBase:
    """Cria o adaptador correspondente a ``canal`` com o ``transporte`` dado."""
    try:
        classe = ADAPTADORES[canal]
    except KeyError:  # pragma: no cover - canal fora do enum
        raise ValueError(f"canal não suportado: {canal!r}") from None
    return classe(transporte, timeout=timeout)


# Alias de tipo para uso externo (ex.: anotações na política de retry 8.2).
CanalConcreto = _CanalBase

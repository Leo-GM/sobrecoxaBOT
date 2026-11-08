"""Política de notificação com retry e preservação de ocorrências.

Implementa o contrato ``nucleo.Notificador`` (seção *Components and Interfaces*
do design) orquestrando o envio por um ``CanalNotificacao`` com a política de
retry definida na seção *Error Handling*::

    Envio de notificação falha ou excede 30s  -> registra falha (data/hora/canal)
    retry a cada 10 min, até 3 adicionais      -> 4 tentativas no total (Req 4.5, 4.6)
    3 retries de envio falham                  -> falha definitiva; informa o usuário;
                                                  preserva ocorrências (Req 4.7)

Decisões de projeto desta camada:

* **Fonte do tempo injetável.** O backoff de 10 minutos entre tentativas é
  aplicado por uma função ``dormir(segundos)`` injetável. Em produção usa
  ``time.sleep``; nos testes é substituída por um relógio falso, tornando o
  retry rápido e determinístico (sem ``sleep`` real).
* **Preservação das ocorrências (Property 11 / Req 4.7).** As ocorrências
  detectadas são tratadas como entrada imutável: qualquer que seja o resultado
  do envio — sucesso, falha transitória ou falha definitiva — o registro
  devolvido por ``ultimas_ocorrencias`` reflete exatamente o que foi detectado,
  sem perda ou descarte.
* **Validação de contato / bloqueio sem canal (Req 4.8, 4.9).** Antes de
  qualquer envio o ``Dado_de_Contato`` é validado pelo canal (reuso de
  ``validar_contato``). Um contato inválido é rejeitado sem acionar o
  transporte; a ativação do monitoramento é bloqueada enquanto não houver um
  canal/contato válido (``validar_ativacao``).

A geração do texto das mensagens é delegada ao módulo ``mensagens`` e os
adaptadores de canal ao módulo ``canais`` (tarefa 8.1).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Mapping, Sequence

from notificacoes_ru.nucleo.modelos import Ocorrencia, Prato_Monitorado
from notificacoes_ru.nucleo.resultados import ResultadoEnvio
from notificacoes_ru.nucleo.tipos import Dado_de_Contato

from notificacoes_ru.notificacao.canais import CanalConcreto
from notificacoes_ru.notificacao.mensagens import (
    mensagem_falha_coleta,
    mensagem_lembrete_dia,
    mensagem_ocorrencias,
    mensagem_sem_ocorrencias,
    validar_contato,
)

# Intervalo entre tentativas de envio: 10 minutos (Req 4.6).
INTERVALO_RETRY_SEGUNDOS: float = 10 * 60

# Número de tentativas adicionais após a primeira falha (Req 4.6):
# 1 tentativa inicial + 3 retries = 4 tentativas no total.
MAX_RETRIES: int = 3


# Função de espera entre tentativas (injetável para testes determinísticos).
FuncaoDormir = Callable[[float], None]

# Função que fornece o instante atual do registro de falha (injetável).
FuncaoAgora = Callable[[], datetime]


@dataclass(frozen=True)
class RegistroFalha:
    """Registro de uma falha de envio: data/hora, canal e motivo (Req 4.5)."""

    quando: datetime
    canal: str
    motivo: str


@dataclass
class ResultadoNotificacao:
    """Resultado observável de uma operação de notificação.

    * ``entregue``        — ``True`` se algum envio teve sucesso dentro das
      4 tentativas.
    * ``tentativas``      — número de tentativas de envio efetuadas (1 a 4).
    * ``falhas``          — registros de cada tentativa malsucedida (Req 4.5).
    * ``falha_definitiva``— ``True`` quando as 4 tentativas falharam (Req 4.7).
    * ``ocorrencias``     — as ocorrências detectadas, preservadas intactas
      qualquer que tenha sido o resultado do envio (Property 11 / Req 4.7).
    """

    entregue: bool
    tentativas: int
    falhas: list[RegistroFalha] = field(default_factory=list)
    falha_definitiva: bool = False
    ocorrencias: Mapping[Prato_Monitorado, Sequence[Ocorrencia]] | None = None


class NotificadorComRetry:
    """``Notificador`` concreto: envia por um canal com retry (Req 4).

    Orquestra um ``CanalNotificacao`` (os adaptadores da tarefa 8.1) aplicando a
    política de retry a cada 10 minutos por até 3 tentativas adicionais e
    preservando o registro das ocorrências detectadas independentemente do
    resultado do envio.
    """

    def __init__(
        self,
        canal: CanalConcreto,
        *,
        dormir: FuncaoDormir = _time.sleep,
        agora: FuncaoAgora = datetime.now,
        intervalo_retry: float = INTERVALO_RETRY_SEGUNDOS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._canal = canal
        self._dormir = dormir
        self._agora = agora
        self._intervalo_retry = intervalo_retry
        self._max_retries = max_retries
        # Última leitura preservada das ocorrências detectadas (Req 4.7).
        self._ultimas_ocorrencias: (
            Mapping[Prato_Monitorado, Sequence[Ocorrencia]] | None
        ) = None

    # ------------------------------------------------------------------
    # Preservação de ocorrências (Property 11 / Req 4.7)
    # ------------------------------------------------------------------
    def ultimas_ocorrencias(
        self,
    ) -> Mapping[Prato_Monitorado, Sequence[Ocorrencia]] | None:
        """Devolve as últimas ocorrências detectadas, preservadas intactas.

        O valor reflete exatamente o conjunto detectado passado à última
        chamada de ``notificar_ocorrencias``, sem alteração — qualquer que
        tenha sido o resultado do envio (Property 11).
        """
        return self._ultimas_ocorrencias

    # ------------------------------------------------------------------
    # Validação de ativação (Req 4.8, 4.9)
    # ------------------------------------------------------------------
    @staticmethod
    def validar_ativacao(contato: Dado_de_Contato | None) -> bool:
        """Indica se o monitoramento pode ser ativado com ``contato`` (Req 4.9).

        A ativação só é permitida com um ``Dado_de_Contato`` presente e no
        formato válido do canal; caso contrário é bloqueada (Req 4.8, 4.9).
        """
        if contato is None:
            return False
        return validar_contato(contato)

    # ------------------------------------------------------------------
    # Contrato Notificador
    # ------------------------------------------------------------------
    def notificar_ocorrencias(
        self,
        ocorrencias: Mapping[Prato_Monitorado, Sequence[Ocorrencia]],
        canal: object = None,  # compatível com a assinatura do Protocol
        contato: Dado_de_Contato | None = None,
    ) -> ResultadoNotificacao:
        """Notifica as ocorrências encontradas com retry (Req 4.1, 4.5–4.7).

        Preserva o registro de ``ocorrencias`` independentemente do resultado
        do envio (Property 11): mesmo após falha definitiva, as ocorrências
        permanecem acessíveis via ``ultimas_ocorrencias``.
        """
        # Preserva as ocorrências ANTES de qualquer tentativa de envio, de modo
        # que elas sobrevivam inclusive a uma falha definitiva (Req 4.7).
        self._ultimas_ocorrencias = ocorrencias

        texto = mensagem_ocorrencias(ocorrencias)
        resultado = self._enviar_com_retry(texto, contato)
        resultado.ocorrencias = ocorrencias
        return resultado

    def notificar_sem_ocorrencias(
        self,
        canal: object = None,
        contato: Dado_de_Contato | None = None,
    ) -> ResultadoNotificacao:
        """Notifica que nenhum prato foi encontrado na semana (Req 4.4)."""
        return self._enviar_com_retry(mensagem_sem_ocorrencias(), contato)

    def notificar_falha_coleta(
        self,
        canal: object = None,
        contato: Dado_de_Contato | None = None,
    ) -> ResultadoNotificacao:
        """Notifica que o cardápio da semana não pôde ser obtido (Req 1.6)."""
        return self._enviar_com_retry(mensagem_falha_coleta(), contato)

    def notificar_lembrete_dia(
        self,
        prato_nome: str,
        refeicoes: Sequence[str],
        canal: object = None,
        contato: Dado_de_Contato | None = None,
    ) -> ResultadoNotificacao:
        """Envia o lembrete diário de que o prato é servido hoje (Opção 1).

        Usa a mesma política de retry e validação de contato dos demais envios:
        um contato ausente/ inválido é bloqueado sem acionar o transporte.
        """
        texto = mensagem_lembrete_dia(prato_nome, refeicoes)
        return self._enviar_com_retry(texto, contato)

    # ------------------------------------------------------------------
    # Núcleo do retry
    # ------------------------------------------------------------------
    def _enviar_com_retry(
        self,
        mensagem: str,
        contato: Dado_de_Contato | None,
    ) -> ResultadoNotificacao:
        """Tenta enviar ``mensagem`` aplicando a política de retry.

        Faz 1 tentativa inicial + até ``max_retries`` adicionais, aguardando
        ``intervalo_retry`` segundos (padrão 10 min) entre elas. Cada falha é
        registrada com data/hora, canal e motivo (Req 4.5). Interrompe assim
        que um envio tem sucesso; marca falha definitiva se todas falharem
        (Req 4.7).
        """
        # Contato ausente/ inválido é bloqueio de configuração (Req 4.8/4.9):
        # não aciona o transporte e não conta como tentativa de envio.
        if contato is None or not validar_contato(contato):
            canal_nome = contato.canal.value if contato is not None else "desconhecido"
            registro = RegistroFalha(
                quando=self._agora(),
                canal=canal_nome,
                motivo="contato ausente ou inválido para o canal",
            )
            return ResultadoNotificacao(
                entregue=False,
                tentativas=0,
                falhas=[registro],
                falha_definitiva=True,
            )

        falhas: list[RegistroFalha] = []
        total_tentativas = self._max_retries + 1  # inicial + adicionais

        for numero in range(total_tentativas):
            if numero > 0:
                # Backoff de 10 min antes de cada retry (Req 4.6). A espera é
                # delegada à função injetável — em testes, um relógio falso.
                self._dormir(self._intervalo_retry)

            resultado: ResultadoEnvio = self._canal.enviar(contato, mensagem)

            if resultado.sucesso:
                return ResultadoNotificacao(
                    entregue=True,
                    tentativas=numero + 1,
                    falhas=falhas,
                    falha_definitiva=False,
                )

            falhas.append(
                RegistroFalha(
                    quando=self._agora(),
                    canal=contato.canal.value,
                    motivo=resultado.motivo or "falha de envio",
                )
            )

        # Todas as tentativas (1 inicial + 3 adicionais) falharam: falha
        # definitiva informada ao usuário, ocorrências preservadas (Req 4.7).
        return ResultadoNotificacao(
            entregue=False,
            tentativas=total_tentativas,
            falhas=falhas,
            falha_definitiva=True,
        )

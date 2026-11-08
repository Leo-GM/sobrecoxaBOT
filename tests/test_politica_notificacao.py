"""Testes da política de notificação com retry (tarefa 8.2).

Cobrem o contrato ``nucleo.Notificador`` concretizado por ``NotificadorComRetry``:

* retry a cada 10 min por até 3 tentativas adicionais (Req 4.5, 4.6);
* falha definitiva após as 4 tentativas, informada ao usuário (Req 4.7);
* preservação do registro de ocorrências independentemente do envio
  (Property 11 / Req 4.7);
* validação de contato por canal e bloqueio de ativação sem canal válido
  (Req 4.8, 4.9);
* registro de falha com data/hora/canal (Req 4.5).

O tempo é simulado por uma função ``dormir`` falsa (sem ``sleep`` real) e o
transporte dos canais é um duble offline/determinístico.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from notificacoes_ru.nucleo.modelos import Ocorrencia, Prato_Monitorado
from notificacoes_ru.nucleo.resultados import ResultadoEnvio
from notificacoes_ru.nucleo.tipos import Canal_de_Notificacao, Dado_de_Contato, Refeicao
from notificacoes_ru.notificacao.canais import NotificadorEmail, NotificadorWhatsApp
from notificacoes_ru.notificacao.politica import (
    INTERVALO_RETRY_SEGUNDOS,
    MAX_RETRIES,
    NotificadorComRetry,
)


# ---------------------------------------------------------------------------
# Dubles offline / relógio falso
# ---------------------------------------------------------------------------


class RelogioFalso:
    """Acumula as esperas solicitadas sem dormir de fato (tempo simulado)."""

    def __init__(self) -> None:
        self.esperas: list[float] = []

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)


class CanalSequencia:
    """Canal falso que devolve ``ResultadoEnvio`` de uma sequência pré-definida.

    Permite modelar falhas transitórias seguidas (ou não) de sucesso, sem
    depender de transporte real.
    """

    def __init__(self, resultados: list[ResultadoEnvio]) -> None:
        self._resultados = list(resultados)
        self.chamadas: list[tuple[Dado_de_Contato, str]] = []

    def enviar(self, destino: Dado_de_Contato, mensagem: str) -> ResultadoEnvio:
        self.chamadas.append((destino, mensagem))
        if self._resultados:
            return self._resultados.pop(0)
        return ResultadoEnvio(sucesso=False, motivo="sem mais resultados")


def _falha(motivo: str = "provedor indisponível") -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=False, motivo=motivo)


def _ok() -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=True)


_CONTATO = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "aluno@unicamp.br")


def _ocorrencias() -> dict[Prato_Monitorado, list[Ocorrencia]]:
    prato = Prato_Monitorado("Sobrecoxa de frango", "sobrecoxa de frango")
    return {
        prato: [
            Ocorrencia("segunda", Refeicao.ALMOCO, "RU", date(2024, 3, 11)),
            Ocorrencia("quarta", Refeicao.JANTAR, "RA", date(2024, 3, 11)),
        ]
    }


# ---------------------------------------------------------------------------
# Retry (Req 4.5, 4.6)
# ---------------------------------------------------------------------------


def test_sucesso_na_primeira_tentativa_nao_faz_retry() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_sem_ocorrencias(contato=_CONTATO)

    assert resultado.entregue is True
    assert resultado.tentativas == 1
    assert resultado.falha_definitiva is False
    assert len(canal.chamadas) == 1
    assert relogio.esperas == []  # nenhum backoff


def test_retry_ate_suceder_registra_falhas_e_espera_10min() -> None:
    relogio = RelogioFalso()
    # Falha, falha, sucesso na 3ª tentativa.
    canal = CanalSequencia([_falha(), _falha(), _ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_sem_ocorrencias(contato=_CONTATO)

    assert resultado.entregue is True
    assert resultado.tentativas == 3
    assert resultado.falha_definitiva is False
    assert len(resultado.falhas) == 2
    assert len(canal.chamadas) == 3
    # Dois backoffs de 10 minutos entre as três tentativas.
    assert relogio.esperas == [INTERVALO_RETRY_SEGUNDOS, INTERVALO_RETRY_SEGUNDOS]


def test_quatro_tentativas_todas_falham_falha_definitiva() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_falha(), _falha(), _falha(), _falha()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_sem_ocorrencias(contato=_CONTATO)

    assert resultado.entregue is False
    assert resultado.falha_definitiva is True
    # 1 inicial + 3 adicionais = 4 tentativas (Req 4.6).
    assert resultado.tentativas == MAX_RETRIES + 1 == 4
    assert len(canal.chamadas) == 4
    assert len(resultado.falhas) == 4
    # Exatamente 3 backoffs de 10 minutos (entre as 4 tentativas).
    assert relogio.esperas == [INTERVALO_RETRY_SEGUNDOS] * MAX_RETRIES


def test_registro_de_falha_tem_data_hora_e_canal() -> None:
    instante = datetime(2024, 3, 11, 7, 0, 0)
    relogio = RelogioFalso()
    canal = CanalSequencia([_falha("timeout"), _ok()])
    notificador = NotificadorComRetry(
        canal, dormir=relogio.dormir, agora=lambda: instante
    )

    resultado = notificador.notificar_sem_ocorrencias(contato=_CONTATO)

    assert len(resultado.falhas) == 1
    registro = resultado.falhas[0]
    assert registro.quando == instante
    assert registro.canal == Canal_de_Notificacao.EMAIL.value
    assert registro.motivo == "timeout"


# ---------------------------------------------------------------------------
# Preservação de ocorrências (Property 11 / Req 4.7)
# ---------------------------------------------------------------------------


def test_ocorrencias_preservadas_apos_falha_definitiva() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_falha(), _falha(), _falha(), _falha()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)
    ocorrencias = _ocorrencias()

    resultado = notificador.notificar_ocorrencias(ocorrencias, contato=_CONTATO)

    assert resultado.falha_definitiva is True
    # As ocorrências detectadas são preservadas intactas (Req 4.7).
    assert resultado.ocorrencias == ocorrencias
    assert notificador.ultimas_ocorrencias() == ocorrencias


def test_ocorrencias_preservadas_apos_sucesso() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)
    ocorrencias = _ocorrencias()

    resultado = notificador.notificar_ocorrencias(ocorrencias, contato=_CONTATO)

    assert resultado.entregue is True
    assert resultado.ocorrencias == ocorrencias
    assert notificador.ultimas_ocorrencias() == ocorrencias


# ---------------------------------------------------------------------------
# Validação de contato / bloqueio de ativação (Req 4.8, 4.9)
# ---------------------------------------------------------------------------


def test_contato_invalido_bloqueia_envio_sem_acionar_canal() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)
    invalido = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "sem-arroba")

    resultado = notificador.notificar_sem_ocorrencias(contato=invalido)

    assert resultado.entregue is False
    assert resultado.falha_definitiva is True
    assert resultado.tentativas == 0
    assert canal.chamadas == []  # canal nunca acionado
    assert relogio.esperas == []


def test_contato_ausente_bloqueia_envio() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_sem_ocorrencias(contato=None)

    assert resultado.entregue is False
    assert resultado.tentativas == 0
    assert canal.chamadas == []


def test_validar_ativacao_aceita_so_contato_valido() -> None:
    valido = Dado_de_Contato(Canal_de_Notificacao.WHATSAPP, "+5519999998888")
    invalido = Dado_de_Contato(Canal_de_Notificacao.WHATSAPP, "telefone")

    assert NotificadorComRetry.validar_ativacao(valido) is True
    assert NotificadorComRetry.validar_ativacao(invalido) is False
    assert NotificadorComRetry.validar_ativacao(None) is False


# ---------------------------------------------------------------------------
# Integração com os adaptadores reais (8.1) + transporte offline
# ---------------------------------------------------------------------------


def test_integracao_com_adaptador_real_transporte_falha_depois_sucede() -> None:
    """A política orquestra um adaptador real (NotificadorEmail) via transporte."""
    estado = {"tentativas": 0}

    def transporte(destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
        estado["tentativas"] += 1
        if estado["tentativas"] < 3:
            raise RuntimeError("provedor indisponível")

    relogio = RelogioFalso()
    canal = NotificadorEmail(transporte)
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_sem_ocorrencias(contato=_CONTATO)

    assert resultado.entregue is True
    assert resultado.tentativas == 3
    assert estado["tentativas"] == 3
    assert len(resultado.falhas) == 2


# ---------------------------------------------------------------------------
# Lembrete diário (Opção 1)
# ---------------------------------------------------------------------------


def test_notificar_lembrete_dia_sucesso_primeira_tentativa() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)

    resultado = notificador.notificar_lembrete_dia(
        "Sobrecoxa", [Refeicao.ALMOCO.value], contato=_CONTATO
    )

    assert resultado.entregue is True
    assert resultado.tentativas == 1
    assert resultado.falha_definitiva is False
    assert len(canal.chamadas) == 1
    # A mensagem enviada é o lembrete do prato.
    _, mensagem = canal.chamadas[0]
    assert "SOBRECOXA" in mensagem
    assert relogio.esperas == []


def test_notificar_lembrete_dia_contato_invalido_bloqueia() -> None:
    relogio = RelogioFalso()
    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal, dormir=relogio.dormir)
    invalido = Dado_de_Contato(Canal_de_Notificacao.EMAIL, "sem-arroba")

    resultado = notificador.notificar_lembrete_dia(
        "Sobrecoxa", [Refeicao.ALMOCO.value], contato=invalido
    )

    assert resultado.entregue is False
    assert resultado.falha_definitiva is True
    assert resultado.tentativas == 0
    assert canal.chamadas == []  # transporte nunca acionado


def test_satisfaz_contrato_notificador() -> None:
    import notificacoes_ru.nucleo as nucleo

    canal = CanalSequencia([_ok()])
    notificador = NotificadorComRetry(canal)
    assert isinstance(notificador, nucleo.Notificador)

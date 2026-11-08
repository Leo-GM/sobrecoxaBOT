"""Smoke tests do setup do projeto (tarefa 1).

Verificam que a estrutura de pacotes e os contratos conceituais importam e que
o framework de testes (pytest + Hypothesis) está operacional. Não exercitam
regra de negócio — nenhuma implementação existe ainda nesta fase.
"""

from __future__ import annotations

import importlib

from hypothesis import given
from hypothesis import strategies as st

import notificacoes_ru.nucleo as nucleo


def test_subpacotes_importam() -> None:
    for sub in ("nucleo", "coleta", "persistencia", "notificacao", "agendamento", "web"):
        importlib.import_module(f"notificacoes_ru.{sub}")


def test_contratos_sao_protocols_runtime_checkable() -> None:
    # Um objeto sem os métodos não deve satisfazer os contratos.
    class Vazio:
        pass

    assert not isinstance(Vazio(), nucleo.Coletor)
    assert not isinstance(Vazio(), nucleo.Detector)
    assert not isinstance(Vazio(), nucleo.Notificador)
    assert not isinstance(Vazio(), nucleo.HistoricoRepo)
    assert not isinstance(Vazio(), nucleo.ConfigRepo)
    assert not isinstance(Vazio(), nucleo.CofreCredenciais)
    assert not isinstance(Vazio(), nucleo.Agendador)
    assert not isinstance(Vazio(), nucleo.CanalNotificacao)


def test_enums_do_dominio() -> None:
    assert nucleo.Refeicao.ALMOCO.value == "almoço"
    assert nucleo.Refeicao.JANTAR.value == "jantar"
    assert {c.value for c in nucleo.Canal_de_Notificacao} == {"WhatsApp", "Telegram", "e-mail"}


@given(st.text())
def test_hypothesis_operacional(texto: str) -> None:
    # Confirma apenas que o Hypothesis executa um teste de propriedade.
    assert isinstance(texto, str)

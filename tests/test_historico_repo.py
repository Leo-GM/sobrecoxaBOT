"""Testes unitários do ``HistoricoSQLite`` (Tarefa 3.7).

Cobrem o round trip de ``salvar``/``buscar_por_intervalo``, a ordenação e os
limites do intervalo (Req 5.1), a busca por prato insensível a caixa/acentuação
restrita ao intervalo (Req 5.2), o ranking limitado e não crescente (Req 5.4) e
a política de retenção mínima de 12 meses (Req 5.7). São testes de exemplo que
complementam os testes de propriedade das subtarefas 3.8–3.11.
"""

from __future__ import annotations

from datetime import date

import pytest

from notificacoes_ru.nucleo.contratos import HistoricoRepo
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, ItemCardapio
from notificacoes_ru.nucleo.tipos import Refeicao
from notificacoes_ru.persistencia.esquema import conectar, inicializar_banco
from notificacoes_ru.persistencia.historico import HistoricoSQLite


@pytest.fixture()
def repo() -> HistoricoSQLite:
    """Repositório sobre um banco SQLite em memória, isolado por teste."""
    conexao = inicializar_banco(conexao=conectar(":memory:"))
    return HistoricoSQLite(conexao)


def _cardapio(
    restaurante: str,
    data_coleta: date,
    itens: tuple[ItemCardapio, ...] = (),
    semana_ano: int = 1,
) -> Cardapio_Semanal:
    return Cardapio_Semanal(
        restaurante=restaurante,
        data_coleta=data_coleta,
        semana_ano=semana_ano,
        itens=itens,
    )


def _item(dia: str, refeicao: Refeicao, texto: str) -> ItemCardapio:
    return ItemCardapio(dia_semana=dia, refeicao=refeicao, texto_item=texto)


def test_satisfaz_contrato_historico_repo(repo: HistoricoSQLite) -> None:
    assert isinstance(repo, HistoricoRepo)


def test_salvar_e_buscar_por_intervalo_round_trip(repo: HistoricoSQLite) -> None:
    itens = (
        _item("segunda", Refeicao.ALMOCO, "Sobrecoxa de frango assada"),
        _item("terca", Refeicao.JANTAR, "Arroz integral"),
    )
    cardapio = _cardapio("RU", date(2024, 3, 11), itens, semana_ano=11)
    repo.salvar(cardapio, date(2024, 3, 11), "RU")

    resultado = repo.buscar_por_intervalo(date(2024, 3, 1), date(2024, 3, 31))

    assert len(resultado) == 1
    recuperado = resultado[0]
    assert recuperado.restaurante == "RU"
    assert recuperado.data_coleta == date(2024, 3, 11)
    assert recuperado.semana_ano == 11
    assert recuperado.itens == itens


def test_buscar_por_intervalo_ordena_crescente(repo: HistoricoSQLite) -> None:
    repo.salvar(_cardapio("RU", date(2024, 5, 20)), date(2024, 5, 20), "RU")
    repo.salvar(_cardapio("RU", date(2024, 5, 6)), date(2024, 5, 6), "RU")
    repo.salvar(_cardapio("RU", date(2024, 5, 13)), date(2024, 5, 13), "RU")

    datas = [c.data_coleta for c in repo.buscar_por_intervalo(date(2024, 5, 1), date(2024, 5, 31))]

    assert datas == [date(2024, 5, 6), date(2024, 5, 13), date(2024, 5, 20)]


def test_buscar_por_intervalo_inclui_as_pontas_e_exclui_fora(repo: HistoricoSQLite) -> None:
    repo.salvar(_cardapio("RU", date(2024, 1, 1)), date(2024, 1, 1), "RU")
    repo.salvar(_cardapio("RU", date(2024, 1, 31)), date(2024, 1, 31), "RU")
    repo.salvar(_cardapio("RU", date(2023, 12, 31)), date(2023, 12, 31), "RU")
    repo.salvar(_cardapio("RU", date(2024, 2, 1)), date(2024, 2, 1), "RU")

    datas = [c.data_coleta for c in repo.buscar_por_intervalo(date(2024, 1, 1), date(2024, 1, 31))]

    assert datas == [date(2024, 1, 1), date(2024, 1, 31)]


def test_salvar_substitui_cardapio_da_mesma_chave(repo: HistoricoSQLite) -> None:
    antigo = _cardapio("RU", date(2024, 4, 1), (_item("segunda", Refeicao.ALMOCO, "Feijoada"),))
    repo.salvar(antigo, date(2024, 4, 1), "RU")

    novo = _cardapio("RU", date(2024, 4, 1), (_item("segunda", Refeicao.ALMOCO, "Strogonoff"),))
    repo.salvar(novo, date(2024, 4, 1), "RU")

    resultado = repo.buscar_por_intervalo(date(2024, 4, 1), date(2024, 4, 1))
    assert len(resultado) == 1
    assert resultado[0].itens[0].texto_item == "Strogonoff"


def test_buscar_por_prato_insensivel_a_caixa_e_acento(repo: HistoricoSQLite) -> None:
    itens = (
        _item("segunda", Refeicao.ALMOCO, "SOBRECOXA de Frango"),
        _item("terca", Refeicao.JANTAR, "Filé de peixe"),
    )
    repo.salvar(_cardapio("RU", date(2024, 6, 3), itens), date(2024, 6, 3), "RU")

    ocorrencias = repo.buscar_por_prato("sobrecóxa", date(2024, 6, 1), date(2024, 6, 30))

    assert len(ocorrencias) == 1
    oc = ocorrencias[0]
    assert oc.dia_semana == "segunda"
    assert oc.refeicao == Refeicao.ALMOCO
    assert oc.restaurante == "RU"
    assert oc.data_coleta == date(2024, 6, 3)


def test_buscar_por_prato_restrito_ao_intervalo(repo: HistoricoSQLite) -> None:
    dentro = (_item("segunda", Refeicao.ALMOCO, "Sobrecoxa"),)
    fora = (_item("segunda", Refeicao.ALMOCO, "Sobrecoxa"),)
    repo.salvar(_cardapio("RU", date(2024, 6, 10), dentro), date(2024, 6, 10), "RU")
    repo.salvar(_cardapio("RU", date(2024, 8, 10), fora), date(2024, 8, 10), "RU")

    ocorrencias = repo.buscar_por_prato("sobrecoxa", date(2024, 6, 1), date(2024, 6, 30))

    assert [o.data_coleta for o in ocorrencias] == [date(2024, 6, 10)]


def test_ranking_mais_servidos_limitado_e_nao_crescente(repo: HistoricoSQLite) -> None:
    # Arroz x3, Feijao x2, Salada x1 dentro do intervalo.
    repo.salvar(
        _cardapio(
            "RU",
            date(2024, 7, 1),
            (
                _item("segunda", Refeicao.ALMOCO, "Arroz"),
                _item("terca", Refeicao.ALMOCO, "Arroz"),
                _item("quarta", Refeicao.ALMOCO, "Arroz"),
                _item("segunda", Refeicao.JANTAR, "Feijao"),
                _item("terca", Refeicao.JANTAR, "Feijao"),
                _item("quarta", Refeicao.JANTAR, "Salada"),
            ),
        ),
        date(2024, 7, 1),
        "RU",
    )

    ranking = repo.ranking_mais_servidos(date(2024, 7, 1), date(2024, 7, 31))

    frequencias = [freq for _, freq in ranking]
    assert frequencias == sorted(frequencias, reverse=True)
    assert ("Arroz", 3) in ranking
    assert ("Feijao", 2) in ranking
    assert ("Salada", 1) in ranking


def test_ranking_respeita_limite(repo: HistoricoSQLite) -> None:
    itens = tuple(
        _item("segunda", Refeicao.ALMOCO, f"Prato {n}") for n in range(30)
    )
    repo.salvar(_cardapio("RU", date(2024, 9, 2), itens), date(2024, 9, 2), "RU")

    ranking = repo.ranking_mais_servidos(date(2024, 9, 1), date(2024, 9, 30), limite=5)

    assert len(ranking) == 5


def test_ranking_agrupa_por_texto_normalizado(repo: HistoricoSQLite) -> None:
    repo.salvar(
        _cardapio(
            "RU",
            date(2024, 10, 7),
            (
                _item("segunda", Refeicao.ALMOCO, "Sobrecoxa de Frango"),
                _item("terca", Refeicao.ALMOCO, "SOBRECOXA DE FRANGO"),
                _item("quarta", Refeicao.JANTAR, "sobrecóxa de frango"),
            ),
        ),
        date(2024, 10, 7),
        "RU",
    )

    ranking = repo.ranking_mais_servidos(date(2024, 10, 1), date(2024, 10, 31))

    assert len(ranking) == 1
    assert ranking[0][1] == 3


def test_retencao_preserva_ultimos_12_meses_e_remove_antigos(repo: HistoricoSQLite) -> None:
    hoje = date(2024, 6, 15)
    recente = date(2023, 7, 1)        # dentro dos últimos 12 meses
    limite_exato = date(2023, 6, 15)  # exatamente 12 meses atrás (preservado)
    antigo = date(2023, 6, 14)        # mais de 12 meses (removido)

    repo.salvar(_cardapio("RU", recente), recente, "RU")
    repo.salvar(_cardapio("RU", limite_exato), limite_exato, "RU")
    repo.salvar(_cardapio("RU", antigo), antigo, "RU")

    removidos = repo.aplicar_retencao(referencia=hoje)

    datas = [c.data_coleta for c in repo.buscar_por_intervalo(date(2000, 1, 1), hoje)]
    assert removidos == 1
    assert recente in datas
    assert limite_exato in datas
    assert antigo not in datas

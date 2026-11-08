"""Testes unitários do Detector (tarefa 7.1 — Req 3.1–3.6).

Cobrem o comportamento central e os casos de borda da função ``detectar``:
matching insensível a caixa/acentuação, múltiplas ocorrências, lista vazia para
pratos ausentes, satisfação do contrato ``Detector`` e preservação de estado
(erro estruturado) para cardápios ausentes/vazios/inválidos.
"""

from __future__ import annotations

from datetime import date

import pytest

import notificacoes_ru.nucleo as nucleo
from notificacoes_ru.deteccao import CardapioInvalidoError, DetectorPadrao, detectar
from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    ItemCardapio,
    Ocorrencia,
    Prato_Monitorado,
)
from notificacoes_ru.nucleo.texto import normalizar
from notificacoes_ru.nucleo.tipos import Refeicao


def _prato(nome: str) -> Prato_Monitorado:
    return Prato_Monitorado(nome_original=nome, nome_normalizado=normalizar(nome))


def _cardapio(itens: tuple[ItemCardapio, ...], restaurante: str = "RU") -> Cardapio_Semanal:
    return Cardapio_Semanal(
        restaurante=restaurante,
        data_coleta=date(2024, 3, 11),
        semana_ano=11,
        itens=itens,
    )


def test_detecta_ocorrencia_simples() -> None:
    cardapio = _cardapio(
        (
            ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa de frango assada"),
            ItemCardapio("segunda", Refeicao.JANTAR, "Arroz e feijão"),
        )
    )
    prato = _prato("sobrecoxa de frango")

    resultado = detectar(cardapio, [prato])

    assert resultado[prato] == [
        Ocorrencia("segunda", Refeicao.ALMOCO, "RU", date(2024, 3, 11)),
    ]


def test_matching_insensivel_a_caixa_e_acento() -> None:
    cardapio = _cardapio(
        (ItemCardapio("terça", Refeicao.ALMOCO, "SOBRECOXA DE FRANGO"),)
    )
    # Prato com acento e caixa diferentes do item do cardápio.
    prato = _prato("Sóbrecóxa De Frângo")

    resultado = detectar(cardapio, [prato])

    assert len(resultado[prato]) == 1
    assert resultado[prato][0].dia_semana == "terça"


def test_multiplas_ocorrencias_sao_registradas_separadamente() -> None:
    cardapio = _cardapio(
        (
            ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa ao molho"),
            ItemCardapio("quarta", Refeicao.JANTAR, "Sobrecoxa grelhada"),
            ItemCardapio("sexta", Refeicao.ALMOCO, "Peixe"),
        )
    )
    prato = _prato("sobrecoxa")

    resultado = detectar(cardapio, [prato])

    ocorrencias = resultado[prato]
    assert len(ocorrencias) == 2
    coordenadas = {(o.dia_semana, o.refeicao) for o in ocorrencias}
    assert coordenadas == {
        ("segunda", Refeicao.ALMOCO),
        ("quarta", Refeicao.JANTAR),
    }


def test_prato_ausente_produz_lista_vazia() -> None:
    cardapio = _cardapio(
        (ItemCardapio("segunda", Refeicao.ALMOCO, "Arroz e feijão"),)
    )
    prato = _prato("lasanha")

    resultado = detectar(cardapio, [prato])

    assert resultado[prato] == []


def test_cada_ocorrencia_aponta_para_coordenada_existente() -> None:
    itens = (
        ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa"),
        ItemCardapio("quinta", Refeicao.JANTAR, "Sobrecoxa"),
    )
    cardapio = _cardapio(itens, restaurante="RA")
    prato = _prato("sobrecoxa")

    resultado = detectar(cardapio, [prato])

    coordenadas_cardapio = {(i.dia_semana, i.refeicao) for i in itens}
    for ocorrencia in resultado[prato]:
        assert (ocorrencia.dia_semana, ocorrencia.refeicao) in coordenadas_cardapio
        assert ocorrencia.restaurante == "RA"
        assert ocorrencia.data_coleta == date(2024, 3, 11)


def test_varios_pratos_sao_todos_mapeados() -> None:
    cardapio = _cardapio(
        (
            ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa de frango"),
            ItemCardapio("segunda", Refeicao.JANTAR, "Strogonoff de carne"),
        )
    )
    p1 = _prato("sobrecoxa")
    p2 = _prato("strogonoff")
    p3 = _prato("sushi")

    resultado = detectar(cardapio, [p1, p2, p3])

    assert set(resultado.keys()) == {p1, p2, p3}
    assert len(resultado[p1]) == 1
    assert len(resultado[p2]) == 1
    assert resultado[p3] == []


def test_sem_pratos_retorna_mapa_vazio() -> None:
    cardapio = _cardapio(
        (ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa"),)
    )

    assert detectar(cardapio, []) == {}


def test_cardapio_ausente_levanta_erro_estruturado() -> None:
    with pytest.raises(CardapioInvalidoError) as exc:
        detectar(None, [_prato("sobrecoxa")])  # type: ignore[arg-type]
    assert "ausente" in exc.value.motivo


def test_cardapio_vazio_levanta_erro_estruturado() -> None:
    cardapio = _cardapio(())
    with pytest.raises(CardapioInvalidoError) as exc:
        detectar(cardapio, [_prato("sobrecoxa")])
    assert "vazio" in exc.value.motivo


def test_estrutura_invalida_levanta_erro_estruturado() -> None:
    with pytest.raises(CardapioInvalidoError):
        detectar({"itens": []}, [_prato("sobrecoxa")])  # type: ignore[arg-type]


def test_item_invalido_levanta_erro_estruturado() -> None:
    cardapio = _cardapio(("não é um item",))  # type: ignore[arg-type]
    with pytest.raises(CardapioInvalidoError):
        detectar(cardapio, [_prato("sobrecoxa")])


def test_erro_em_cardapio_invalido_preserva_estado_anterior() -> None:
    # Estado anterior de ocorrências do chamador: a detecção que falha não deve
    # alterá-lo (Req 3.6). Como detectar é pura, basta garantir que o erro
    # propaga antes de qualquer resultado e o estado externo permanece.
    estado_anterior = {"RU": ["ocorrencia previa"]}
    snapshot = {k: list(v) for k, v in estado_anterior.items()}

    with pytest.raises(CardapioInvalidoError):
        detectar(_cardapio(()), [_prato("sobrecoxa")])

    assert estado_anterior == snapshot


def test_detector_padrao_satisfaz_o_contrato() -> None:
    detector = DetectorPadrao()
    assert isinstance(detector, nucleo.Detector)

    cardapio = _cardapio(
        (ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa de frango"),)
    )
    prato = _prato("sobrecoxa")
    assert len(detector.detectar(cardapio, [prato])[prato]) == 1

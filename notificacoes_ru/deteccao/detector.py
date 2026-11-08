"""Detector de pratos monitorados no Cardapio_Semanal (Req 3).

Implementa o contrato ``Detector`` do núcleo. Para cada ``Prato_Monitorado``,
percorre todos os itens do cardápio — cada item carrega o seu
``(dia_semana, refeicao)`` — e usa ``contem`` do Normalizador compartilhado
(matching insensível a caixa/acentuação) para decidir se há ocorrência. Cada
item que contém o prato gera uma ``Ocorrencia`` separada
``(dia_semana, refeicao, restaurante, data_coleta)`` (Req 3.1–3.4).

Pratos sem nenhuma ocorrência recebem uma lista vazia (Req 3.5).

Para um cardápio ausente, vazio ou com estrutura inválida, a detecção é
interrompida com ``CardapioInvalidoError`` e nenhum estado é alterado
(Req 3.6). Como ``detectar`` é uma função pura que apenas produz um novo mapa de
ocorrências, "preservar o estado anterior" significa não devolver nem mutar
qualquer registro de ocorrências: a exceção propaga antes de qualquer produção
de resultado, deixando intacto o que o chamador já tivesse.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    ItemCardapio,
    Ocorrencia,
    Prato_Monitorado,
)
from notificacoes_ru.nucleo.texto import contem
from notificacoes_ru.nucleo.tipos import Refeicao


class CardapioInvalidoError(ValueError):
    """Erro estruturado para cardápio ausente, vazio ou inválido (Req 3.6).

    ``motivo`` descreve a causa da falha para registro/diagnóstico.
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def _validar_cardapio(cardapio: Cardapio_Semanal) -> None:
    """Valida a presença e a estrutura do cardápio.

    Levanta ``CardapioInvalidoError`` quando o cardápio está ausente (``None``),
    não é um ``Cardapio_Semanal``, não tem itens, ou algum item não é um
    ``ItemCardapio`` bem formado. Não altera nenhum estado.
    """
    if cardapio is None:
        raise CardapioInvalidoError("cardápio ausente")

    if not isinstance(cardapio, Cardapio_Semanal):
        raise CardapioInvalidoError("cardápio com estrutura inválida")

    itens = cardapio.itens
    if not itens:
        raise CardapioInvalidoError("cardápio vazio (sem itens de refeição)")

    for item in itens:
        if not isinstance(item, ItemCardapio):
            raise CardapioInvalidoError("item de cardápio com estrutura inválida")
        if not isinstance(item.refeicao, Refeicao):
            raise CardapioInvalidoError("refeição do item de cardápio inválida")
        if not isinstance(item.dia_semana, str) or not isinstance(item.texto_item, str):
            raise CardapioInvalidoError("item de cardápio com campos inválidos")


def _ocorrencia_de(cardapio: Cardapio_Semanal, item: ItemCardapio) -> Ocorrencia:
    """Monta a ``Ocorrencia`` correspondente a um ``item`` do cardápio."""
    return Ocorrencia(
        dia_semana=item.dia_semana,
        refeicao=item.refeicao,
        restaurante=cardapio.restaurante,
        data_coleta=cardapio.data_coleta,
    )


def detectar(
    cardapio: Cardapio_Semanal,
    pratos: Sequence[Prato_Monitorado],
) -> Mapping[Prato_Monitorado, Sequence[Ocorrencia]]:
    """Detecta os ``pratos`` monitorados no ``cardapio`` (Req 3.1–3.6).

    Para cada prato, devolve a lista de ocorrências — uma por item do cardápio
    cujo texto contém o nome do prato segundo ``contem`` (insensível a
    caixa/acentuação). Pratos sem ocorrência recebem lista vazia.

    Levanta ``CardapioInvalidoError`` se o cardápio estiver ausente, vazio ou
    com estrutura inválida, sem produzir qualquer resultado parcial (Req 3.6).
    """
    _validar_cardapio(cardapio)

    resultado: dict[Prato_Monitorado, list[Ocorrencia]] = {}
    for prato in pratos:
        ocorrencias = [
            _ocorrencia_de(cardapio, item)
            for item in cardapio.itens
            if contem(item.texto_item, prato.nome_original)
        ]
        resultado[prato] = ocorrencias

    return resultado


class DetectorPadrao:
    """Implementação padrão do contrato ``Detector`` (Req 3).

    Delega a ``detectar``; existe para compor o sistema por objeto (ex.: no
    wiring do Agendador) satisfazendo o ``Protocol`` ``Detector``.
    """

    def detectar(
        self,
        cardapio: Cardapio_Semanal,
        pratos: Sequence[Prato_Monitorado],
    ) -> Mapping[Prato_Monitorado, Sequence[Ocorrencia]]:
        return detectar(cardapio, pratos)

"""Implementação de ``HistoricoRepo`` sobre SQLite (Tarefa 3.7).

Persiste os ``Cardapio_Semanal`` coletados e oferece as consultas do histórico
descritas na seção *Repositórios de Persistência* do design:

* :meth:`HistoricoSQLite.salvar` — grava um cardápio e seus itens (Req 1.3).
* :meth:`HistoricoSQLite.buscar_por_intervalo` — cardápios dentro de
  ``[data_inicial, data_final]`` ordenados por data crescente (Req 5.1,
  Property 12).
* :meth:`HistoricoSQLite.buscar_por_prato` — ocorrências de itens cujo texto
  contém o termo, usando o Normalizador compartilhado, restritas ao intervalo
  (Req 5.2, Property 13).
* :meth:`HistoricoSQLite.ranking_mais_servidos` — pratos mais frequentes no
  intervalo, no máximo ``limite`` (padrão 20), em ordem não crescente de
  frequência (Req 5.4, Property 14).
* :meth:`HistoricoSQLite.aplicar_retencao` — política de retenção que preserva
  todo cardápio dos últimos 12 meses (Req 5.7, Property 16).

Reusa o esquema de :mod:`notificacoes_ru.persistencia.esquema`, os modelos de
:mod:`notificacoes_ru.nucleo.modelos` e a normalização de texto de
:mod:`notificacoes_ru.nucleo.texto`.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Union

from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    ItemCardapio,
    Ocorrencia,
)
from notificacoes_ru.nucleo.texto import contem, normalizar
from notificacoes_ru.nucleo.tipos import Refeicao, Restaurante_Universitario
from notificacoes_ru.persistencia.esquema import inicializar_banco

# Número de meses da retenção mínima garantida (Req 5.7).
MESES_RETENCAO = 12


def _iso(data: date) -> str:
    """Serializa uma ``date`` para ``YYYY-MM-DD`` (ordenável lexicograficamente)."""
    return data.isoformat()


def _para_data(valor: str) -> date:
    """Converte uma string ``YYYY-MM-DD`` armazenada de volta para ``date``."""
    return date.fromisoformat(valor)


def _subtrair_meses(referencia: date, meses: int) -> date:
    """Retorna a data ``meses`` meses antes de ``referencia``.

    Trata o estouro de dia do mês (ex.: 31 de março - 1 mês) fixando no último
    dia válido do mês alvo. Usado para calcular o limite da janela de retenção
    sem depender de bibliotecas externas.
    """
    total_meses = (referencia.year * 12 + (referencia.month - 1)) - meses
    ano, mes0 = divmod(total_meses, 12)
    mes = mes0 + 1
    # Último dia do mês alvo, para não gerar datas inválidas (ex.: 31/02).
    if mes == 12:
        primeiro_mes_seguinte = date(ano + 1, 1, 1)
    else:
        primeiro_mes_seguinte = date(ano, mes + 1, 1)
    ultimo_dia = (primeiro_mes_seguinte - date.resolution).day
    dia = min(referencia.day, ultimo_dia)
    return date(ano, mes, dia)


class HistoricoSQLite:
    """Repositório do Historico de cardápios (satisfaz ``nucleo.HistoricoRepo``).

    Recebe uma conexão SQLite já configurada (ver
    :func:`notificacoes_ru.persistencia.esquema.conectar`). O esquema é
    garantido de forma idempotente na construção.
    """

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao
        # Garante que as tabelas existem (idempotente); não apaga dados.
        inicializar_banco(conexao=conexao)

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------
    def salvar(
        self,
        cardapio: Cardapio_Semanal,
        data_coleta: date,
        restaurante: Restaurante_Universitario,
    ) -> None:
        """Grava ``cardapio`` com seus itens para ``(restaurante, data_coleta)``.

        Cada cardápio é único por ``(restaurante, data_coleta)``; uma nova
        gravação para a mesma chave substitui o cardápio anterior e seus itens
        (regravação idempotente). Os argumentos ``data_coleta`` e
        ``restaurante`` têm precedência sobre os campos homônimos do objeto
        ``cardapio``, conforme a assinatura do contrato.
        """
        data_iso = _iso(data_coleta)
        with self._con:
            # Remove um cardápio anterior com a mesma chave (e seus itens via
            # ON DELETE CASCADE), evitando duplicatas na regravação.
            self._con.execute(
                "DELETE FROM cardapios WHERE restaurante = ? AND data_coleta = ?;",
                (restaurante, data_iso),
            )
            cursor = self._con.execute(
                "INSERT INTO cardapios (restaurante, data_coleta, semana_ano) "
                "VALUES (?, ?, ?);",
                (restaurante, data_iso, cardapio.semana_ano),
            )
            cardapio_id = cursor.lastrowid
            self._con.executemany(
                "INSERT INTO itens_cardapio "
                "(cardapio_id, dia_semana, refeicao, texto_item) "
                "VALUES (?, ?, ?, ?);",
                [
                    (
                        cardapio_id,
                        item.dia_semana,
                        _valor_refeicao(item.refeicao),
                        item.texto_item,
                    )
                    for item in cardapio.itens
                ],
            )

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def buscar_por_intervalo(
        self,
        data_inicial: date,
        data_final: date,
    ) -> list[Cardapio_Semanal]:
        """Retorna os cardápios com data em ``[data_inicial, data_final]``.

        O intervalo é inclusivo em ambas as pontas e o resultado é ordenado por
        ``data_coleta`` em ordem crescente (Req 5.1, Property 12). Cada cardápio
        é reconstruído com todos os seus itens.
        """
        linhas = self._con.execute(
            "SELECT id, restaurante, data_coleta, semana_ano "
            "FROM cardapios "
            "WHERE data_coleta >= ? AND data_coleta <= ? "
            "ORDER BY data_coleta ASC, id ASC;",
            (_iso(data_inicial), _iso(data_final)),
        ).fetchall()

        cardapios: list[Cardapio_Semanal] = []
        for linha in linhas:
            itens = self._itens_de(linha["id"])
            cardapios.append(
                Cardapio_Semanal(
                    restaurante=linha["restaurante"],
                    data_coleta=_para_data(linha["data_coleta"]),
                    semana_ano=linha["semana_ano"],
                    itens=tuple(itens),
                )
            )
        return cardapios

    def buscar_por_prato(
        self,
        termo: str,
        data_inicial: date,
        data_final: date,
    ) -> list[Ocorrencia]:
        """Retorna as ocorrências de itens cujo texto contém ``termo``.

        A correspondência usa o Normalizador compartilhado
        (:func:`notificacoes_ru.nucleo.texto.contem`), portanto é insensível a
        maiúsculas/minúsculas e a acentuação. Somente itens de cardápios com
        data dentro de ``[data_inicial, data_final]`` são considerados (Req 5.2,
        Property 13). O resultado é ordenado por data crescente para leitura
        estável.
        """
        linhas = self._con.execute(
            "SELECT c.data_coleta AS data_coleta, c.restaurante AS restaurante, "
            "       i.dia_semana AS dia_semana, i.refeicao AS refeicao, "
            "       i.texto_item AS texto_item "
            "FROM itens_cardapio i "
            "JOIN cardapios c ON c.id = i.cardapio_id "
            "WHERE c.data_coleta >= ? AND c.data_coleta <= ? "
            "ORDER BY c.data_coleta ASC, c.id ASC, i.id ASC;",
            (_iso(data_inicial), _iso(data_final)),
        ).fetchall()

        ocorrencias: list[Ocorrencia] = []
        for linha in linhas:
            if contem(linha["texto_item"], termo):
                ocorrencias.append(
                    Ocorrencia(
                        dia_semana=linha["dia_semana"],
                        refeicao=_para_refeicao(linha["refeicao"]),
                        restaurante=linha["restaurante"],
                        data_coleta=_para_data(linha["data_coleta"]),
                    )
                )
        return ocorrencias

    def ranking_mais_servidos(
        self,
        data_inicial: date,
        data_final: date,
        limite: int = 20,
    ) -> list[tuple[str, int]]:
        """Retorna os pratos mais servidos no intervalo, por frequência.

        Agrupa os itens de cardápio pelo texto **normalizado** (de modo que
        variações de caixa/acentuação do mesmo prato contem juntas) e conta
        quantas vezes cada um aparece em cardápios dentro do intervalo. Retorna
        no máximo ``limite`` pares ``(prato, frequencia)`` em ordem não
        crescente de frequência (Req 5.4, Property 14). O rótulo exibido é uma
        das grafias originais do prato.

        ``limite`` menor ou igual a zero resulta em lista vazia.
        """
        if limite <= 0:
            return []

        linhas = self._con.execute(
            "SELECT i.texto_item AS texto_item "
            "FROM itens_cardapio i "
            "JOIN cardapios c ON c.id = i.cardapio_id "
            "WHERE c.data_coleta >= ? AND c.data_coleta <= ? "
            "ORDER BY c.data_coleta ASC, c.id ASC, i.id ASC;",
            (_iso(data_inicial), _iso(data_final)),
        ).fetchall()

        # Agrupamento por texto normalizado, preservando um rótulo original e a
        # ordem de primeira aparição para desempate estável.
        frequencias: dict[str, int] = {}
        rotulos: dict[str, str] = {}
        ordem: dict[str, int] = {}
        for indice, linha in enumerate(linhas):
            texto = linha["texto_item"]
            chave = normalizar(texto)
            if chave not in frequencias:
                frequencias[chave] = 0
                rotulos[chave] = texto
                ordem[chave] = indice
            frequencias[chave] += 1

        # Ordena por frequência decrescente; desempate pela ordem de aparição
        # para um resultado determinístico.
        chaves_ordenadas = sorted(
            frequencias,
            key=lambda chave: (-frequencias[chave], ordem[chave]),
        )
        return [(rotulos[chave], frequencias[chave]) for chave in chaves_ordenadas[:limite]]

    # ------------------------------------------------------------------
    # Retenção
    # ------------------------------------------------------------------
    def aplicar_retencao(self, referencia: date | None = None) -> int:
        """Remove cardápios anteriores à janela de retenção de 12 meses.

        Preserva todo cardápio cuja ``data_coleta`` esteja dentro dos últimos
        ``MESES_RETENCAO`` meses em relação a ``referencia`` (por padrão, a data
        de hoje). Cardápios mais antigos que o limite são removidos junto com
        seus itens (ON DELETE CASCADE). Retorna a quantidade de cardápios
        removidos (Req 5.7, Property 16).
        """
        hoje = referencia if referencia is not None else date.today()
        limite = _subtrair_meses(hoje, MESES_RETENCAO)
        with self._con:
            cursor = self._con.execute(
                "DELETE FROM cardapios WHERE data_coleta < ?;",
                (_iso(limite),),
            )
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    def _itens_de(self, cardapio_id: int) -> list[ItemCardapio]:
        """Lê os itens de um cardápio em ordem estável de inserção."""
        linhas = self._con.execute(
            "SELECT dia_semana, refeicao, texto_item "
            "FROM itens_cardapio WHERE cardapio_id = ? ORDER BY id ASC;",
            (cardapio_id,),
        ).fetchall()
        return [
            ItemCardapio(
                dia_semana=linha["dia_semana"],
                refeicao=_para_refeicao(linha["refeicao"]),
                texto_item=linha["texto_item"],
            )
            for linha in linhas
        ]


def _valor_refeicao(refeicao: Union[Refeicao, str]) -> str:
    """Normaliza uma ``Refeicao`` (ou string) para o valor textual persistido."""
    if isinstance(refeicao, Refeicao):
        return refeicao.value
    return str(refeicao)


def _para_refeicao(valor: str) -> Refeicao:
    """Converte o valor textual persistido de volta para ``Refeicao``.

    Mantém compatibilidade caso o valor armazenado não corresponda a um membro
    conhecido, retornando o próprio texto (o enum é ``str``-based).
    """
    try:
        return Refeicao(valor)
    except ValueError:
        return valor  # type: ignore[return-value]

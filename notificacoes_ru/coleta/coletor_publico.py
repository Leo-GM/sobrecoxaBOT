"""Implementação de ``ColetorPublico`` (Tarefa 6.1).

Coletor da fonte **pública** do cardápio dos Restaurantes Universitários da
Unicamp. Satisfaz o contrato :class:`notificacoes_ru.nucleo.contratos.Coletor`:

    coletar(restaurante) -> ResultadoColeta

Fonte real
----------
A página institucional ``https://www.prefeitura.unicamp.br/cardapio/`` apenas
embute um iframe; o cardápio renderizado server-side (raspável com
``requests`` + ``BeautifulSoup``, sem JS) está em::

    https://sistemas.prefeitura.unicamp.br/apps/cardapio/index.php

Um dia específico é selecionado via querystring ISO ``?d=YYYY-MM-DD``; sem o
parâmetro, o site mostra o dia atual. A página é servida em ``iso-8859-1``
(declarado no meta), então a decodificação precisa respeitar esse encoding.

Estrutura HTML real
-------------------
* Cada refeição é uma ``<h2 class="menu-section-title">`` com texto
  "Almoço", "Almoço Vegano", "Jantar" ou "Jantar Vegano".
* A ``.menu-section`` correspondente contém um ``.menu-item`` com:
  - ``.menu-item-name``        -> prato principal (ex.: "LINGUIÇA AO VINAGRETE");
  - ``.menu-item-description`` -> acompanhamentos separados por ``<br>``,
    seguidos de um bloco "Observações:" (alérgenos/horários) que **não** é
    comida e é descartado.
* O site atualmente serve um único restaurante por dia (há observação "As
  refeições serão servidas no RS"); não há três cardápios RU/RA/RS separados no
  HTML.

Fluxo
-----
1. Para cada dia da semana corrente, busca o HTML de ``?d=YYYY-MM-DD`` com o
   ``ClienteHTTP`` injetado (timeout de 120s — Req 1.2), sem usar a
   ``Credencial_Unicamp``.
2. Parseia cada HTML com ``BeautifulSoup`` e agrega os itens num único
   :class:`~notificacoes_ru.nucleo.modelos.Cardapio_Semanal`.
3. Classifica o resultado:
   * :class:`~notificacoes_ru.nucleo.resultados.Sucesso` — cardápio com itens;
   * :class:`~notificacoes_ru.nucleo.resultados.Vazio` — páginas válidas porém
     sem itens de refeição; **não** é persistido (Req 1.4);
   * :class:`~notificacoes_ru.nucleo.resultados.Falha` — indisponibilidade,
     timeout, erro HTTP ou estrutura inválida (Req 1.5 / 3.6).
4. Em caso de ``Sucesso`` grava no ``HistoricoRepo`` informado (Req 1.3).
   ``Vazio``/``Falha`` nunca persistem.

A camada de rede e o parser são injetáveis para manter os testes
determinísticos e offline (nenhuma chamada de rede real nos testes).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional, Protocol, runtime_checkable

import requests
from bs4 import BeautifulSoup

from notificacoes_ru.nucleo.contratos import HistoricoRepo
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, ItemCardapio
from notificacoes_ru.nucleo.resultados import (
    Falha,
    ResultadoColeta,
    Sucesso,
    Vazio,
)
from notificacoes_ru.nucleo.tipos import Refeicao, Restaurante_Universitario

# URL real do cardápio renderizado server-side (o iframe da página pública).
URL_PADRAO = "https://sistemas.prefeitura.unicamp.br/apps/cardapio/index.php"

# Encoding declarado no meta da página real.
ENCODING_PAGINA = "iso-8859-1"

# Tempo limite de extração por restaurante, em segundos (Req 1.2).
TIMEOUT_SEGUNDOS = 120

# Mapeamento de títulos de seção (``menu-section-title``) para o enum Refeicao.
# As chaves já estão normalizadas (minúsculas, sem acento). As versões vegana e
# não-vegana mapeiam para a mesma Refeicao, mas são mantidas como itens
# separados (não desduplicamos nome de prato por refeição).
_ROTULOS_REFEICAO: dict[str, Refeicao] = {
    "almoco": Refeicao.ALMOCO,
    "almoco vegano": Refeicao.ALMOCO,
    "jantar": Refeicao.JANTAR,
    "jantar vegano": Refeicao.JANTAR,
}

# Nomes de dia da semana em português, indexados por ``date.weekday()``
# (0 = segunda-feira ... 6 = domingo).
_DIAS_SEMANA: tuple[str, ...] = (
    "segunda",
    "terca",
    "quarta",
    "quinta",
    "sexta",
    "sabado",
    "domingo",
)

# Marcador textual que separa acompanhamentos (comida) das observações
# (alérgenos/horários), já normalizado.
_MARCADOR_OBSERVACOES = "observacoes"


@runtime_checkable
class ClienteHTTP(Protocol):
    """Camada mínima de busca de HTML (injetável para testes offline)."""

    def get_html(self, url: str, timeout: int) -> str:
        """Retorna o corpo HTML de ``url`` ou levanta ``ErroColeta``."""
        ...


class ErroColeta(Exception):
    """Falha de rede/HTTP durante a busca do HTML da fonte pública."""


class ClienteRequests:
    """Implementação padrão de :class:`ClienteHTTP` usando ``requests``.

    Força a decodificação em ``iso-8859-1`` (encoding real da página), já que o
    ``requests`` nem sempre detecta corretamente o charset declarado só no meta.
    """

    def __init__(self, sessao: Optional[requests.Session] = None) -> None:
        self._sessao = sessao or requests.Session()

    def get_html(self, url: str, timeout: int) -> str:
        try:
            resposta = self._sessao.get(url, timeout=timeout)
            resposta.raise_for_status()
        except requests.RequestException as exc:  # inclui timeout, HTTP, conexão
            raise ErroColeta(str(exc)) from exc
        # A página declara iso-8859-1 apenas no meta; fixamos o encoding para
        # garantir acentuação correta nos nomes de prato.
        resposta.encoding = ENCODING_PAGINA
        return resposta.text


# Assinatura do parser: (html, restaurante, data_dia) -> lista de itens do dia.
Parser = Callable[[str, date], list[ItemCardapio]]


class EstruturaInvalida(Exception):
    """O HTML não corresponde à estrutura esperada do cardápio (Req 3.6)."""


def _normalizar_rotulo(texto: str) -> str:
    """Normaliza um rótulo de seção para casar de forma tolerante.

    Minúsculas, remoção de acentos e colapso de espaços; suficiente para
    comparar os títulos conhecidos ("Almoço", "Almoço Vegano", ...).
    """
    import unicodedata

    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acentos.casefold().split())


def _nome_dia(data_dia: date) -> str:
    """Nome do dia da semana em português para ``data_dia``."""
    return _DIAS_SEMANA[data_dia.weekday()]


def _resolver_refeicao(rotulo: Optional[str]) -> Optional[Refeicao]:
    """Mapeia um título de seção para ``Refeicao`` de forma tolerante."""
    if not rotulo:
        return None
    return _ROTULOS_REFEICAO.get(_normalizar_rotulo(rotulo))


def _acompanhamentos_antes_observacoes(descricao) -> list[str]:
    """Extrai os acompanhamentos (texto) de ``.menu-item-description``.

    Os acompanhamentos vêm separados por ``<br>`` e são seguidos de um bloco
    "Observações:" (alérgenos/horários) que não é comida. Esta função devolve
    apenas as linhas que vêm **antes** desse marcador.
    """
    if descricao is None:
        return []

    linhas: list[str] = []
    for pedaco in descricao.stripped_strings:
        texto = " ".join(pedaco.split())
        if not texto:
            continue
        if _normalizar_rotulo(texto).startswith(_MARCADOR_OBSERVACOES):
            break
        linhas.append(texto)
    return linhas


def parsear_dia(html: str, data_dia: date) -> list[ItemCardapio]:
    """Parseia o HTML de **um dia** em uma lista de ``ItemCardapio``.

    Percorre cada ``<h2 class="menu-section-title">``, mapeia o título para a
    ``Refeicao`` e extrai, na ``.menu-section`` correspondente, o
    ``.menu-item-name`` (prato principal) e os acompanhamentos de
    ``.menu-item-description`` (parando antes do bloco "Observações:").

    HTML sem nenhum ``menu-section-title`` resulta em
    :class:`EstruturaInvalida` (Req 3.6).
    """
    soup = BeautifulSoup(html, "html.parser")

    titulos = soup.select("h2.menu-section-title")
    if not titulos:
        raise EstruturaInvalida("nenhuma seção 'menu-section-title' encontrada")

    dia_semana = _nome_dia(data_dia)
    itens: list[ItemCardapio] = []

    for titulo in titulos:
        refeicao = _resolver_refeicao(titulo.get_text(strip=True))
        if refeicao is None:
            continue

        # A seção de refeição é o contêiner ancestral ``.menu-section`` ou, na
        # falta dele, os elementos irmãos até o próximo título.
        secao = _secao_da_refeicao(titulo)
        if secao is None:
            continue

        for menu_item in secao.select(".menu-item"):
            nome_el = menu_item.select_one(".menu-item-name")
            if nome_el is None:
                continue
            nome = " ".join(nome_el.get_text(strip=True).split())
            if not nome:
                continue

            # Item principal: o prato (o que importa para a detecção).
            itens.append(
                ItemCardapio(
                    dia_semana=dia_semana,
                    refeicao=refeicao,
                    texto_item=nome,
                )
            )

            # Acompanhamentos (antes de "Observações:") como itens adicionais.
            descricao = menu_item.select_one(".menu-item-description")
            for acompanhamento in _acompanhamentos_antes_observacoes(descricao):
                itens.append(
                    ItemCardapio(
                        dia_semana=dia_semana,
                        refeicao=refeicao,
                        texto_item=acompanhamento,
                    )
                )

    return itens


def _secao_da_refeicao(titulo):
    """Retorna o contêiner ``.menu-section`` associado ao ``titulo``.

    Prefere o ancestral ``.menu-section``; se o título estiver fora dele (ou se
    o container envolver vários títulos), cai num sub-escopo que vai do título
    até o próximo ``menu-section-title`` irmão.
    """
    ancestral = titulo.find_parent(class_="menu-section")
    if ancestral is not None:
        # Garante que o ancestral contém este título e não abraça vários: se
        # houver mais de um título dentro, restringimos ao escopo entre irmãos.
        if len(ancestral.select("h2.menu-section-title")) == 1:
            return ancestral
    return _escopo_entre_irmaos(titulo)


class _EscopoVirtual:
    """Agrupa um conjunto de nós-irmãos e expõe ``.select`` como um contêiner.

    Usado como fallback quando um título de seção não está envolto num
    ``.menu-section`` próprio: coletamos os irmãos entre dois títulos e
    procuramos ``.menu-item`` tanto nos nós quanto nos seus descendentes.
    """

    def __init__(self, nos) -> None:
        self._nos = nos

    def select(self, seletor: str):
        encontrados = []
        for no in self._nos:
            if not hasattr(no, "select"):
                continue
            classes = no.get("class", []) or []
            # O próprio nó pode casar o seletor de classe (ex.: ".menu-item").
            alvo_classe = seletor.lstrip(".")
            if seletor.startswith(".") and alvo_classe in classes:
                encontrados.append(no)
            # ...ou o seletor pode casar algum descendente.
            encontrados.extend(no.select(seletor))
        return encontrados


def _escopo_entre_irmaos(titulo):
    """Coleta os irmãos após ``titulo`` até o próximo título de seção."""
    nos = []
    for irmao in titulo.next_siblings:
        nome = getattr(irmao, "name", None)
        if nome is None:
            continue
        classes = irmao.get("class", []) if hasattr(irmao, "get") else []
        if nome == "h2" and "menu-section-title" in classes:
            break
        nos.append(irmao)
    return _EscopoVirtual(nos)


class ColetorPublico:
    """Coletor da fonte pública do cardápio (satisfaz ``nucleo.Coletor``).

    Parâmetros
    ----------
    historico:
        Repositório opcional onde o cardápio é gravado em caso de sucesso com
        itens (Req 1.3). Quando ``None``, a coleta apenas retorna o resultado
        sem persistir.
    url:
        URL base do cardápio real (por padrão :data:`URL_PADRAO`). Os dias são
        selecionados acrescentando ``?d=YYYY-MM-DD``.
    cliente:
        Camada de busca de HTML. Por padrão usa ``requests``; nos testes é
        substituída por um cliente que devolve HTML de amostra (offline).
    parser:
        Função de parsing de **um dia**. Por padrão :func:`parsear_dia`.
    """

    def __init__(
        self,
        historico: Optional[HistoricoRepo] = None,
        *,
        url: str = URL_PADRAO,
        cliente: Optional[ClienteHTTP] = None,
        parser: Parser = parsear_dia,
    ) -> None:
        self._historico = historico
        self._url = url
        self._cliente = cliente or ClienteRequests()
        self._parser = parser

    def coletar(self, restaurante: Restaurante_Universitario) -> ResultadoColeta:
        """Coleta o cardápio da semana corrente para ``restaurante``.

        Busca os 7 dias da semana ISO corrente via ``?d=YYYY-MM-DD`` e agrega os
        itens num único ``Cardapio_Semanal``. Retorna ``Sucesso`` (com
        persistência), ``Vazio`` (sem persistência, Req 1.4) ou ``Falha``
        (indisponível/timeout/estrutura inválida).
        """
        data_coleta = date.today()
        dias = self._dias_da_semana(data_coleta)

        itens: list[ItemCardapio] = []
        estrutura_valida = False

        for data_dia in dias:
            url = self._url_do_dia(data_dia)

            # 1. Busca do HTML — falhas de rede/HTTP viram Falha (Req 1.5).
            try:
                html = self._cliente.get_html(url, timeout=TIMEOUT_SEGUNDOS)
            except ErroColeta as exc:
                return Falha(motivo=f"falha ao acessar a fonte pública: {exc}")

            # 2. Parsing — estrutura inválida de um dia não derruba a semana
            #    inteira, mas se NENHUM dia tiver estrutura válida, é Falha.
            try:
                itens.extend(self._parser(html, data_dia))
                estrutura_valida = True
            except EstruturaInvalida:
                continue
            except Exception as exc:  # parsing defensivo: qualquer erro é Falha
                return Falha(motivo=f"erro ao parsear o cardápio: {exc}")

        # Nenhum dia com a estrutura esperada -> Falha (Req 3.6).
        if not estrutura_valida:
            return Falha(
                motivo="estrutura inválida do cardápio: nenhuma seção encontrada"
            )

        cardapio = Cardapio_Semanal(
            restaurante=restaurante,
            data_coleta=data_coleta,
            semana_ano=data_coleta.isocalendar().week,
            itens=tuple(itens),
        )

        # 3. Cardápio sem itens é Vazio e NÃO é persistido (Req 1.4).
        if not cardapio.itens:
            return Vazio()

        # 4. Sucesso: persiste no Historico quando houver repositório (Req 1.3).
        if self._historico is not None:
            self._historico.salvar(cardapio, cardapio.data_coleta, restaurante)

        return Sucesso(cardapio=cardapio)

    @staticmethod
    def _dias_da_semana(referencia: date) -> list[date]:
        """Os 7 dias (segunda a domingo) da semana ISO que contém ``referencia``."""
        segunda = referencia - timedelta(days=referencia.weekday())
        return [segunda + timedelta(days=offset) for offset in range(7)]

    def _url_do_dia(self, data_dia: date) -> str:
        """Compõe a URL do dia via querystring ISO ``?d=YYYY-MM-DD``."""
        separador = "&" if "?" in self._url else "?"
        return f"{self._url}{separador}d={data_dia.isoformat()}"

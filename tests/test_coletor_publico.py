"""Testes de ``ColetorPublico`` (Tarefa 6.1).

Cobrem a classificação do ``ResultadoColeta`` e a integração com o
``HistoricoRepo``, usando um cliente HTTP falso para manter tudo offline
(nenhuma chamada de rede real). As amostras de HTML replicam a estrutura
**real** do cardápio renderizado server-side da Unicamp
(``sistemas.prefeitura.unicamp.br/apps/cardapio/index.php``): seções
``<h2 class="menu-section-title">`` (Almoço / Almoço Vegano / Jantar /
Jantar Vegano) com ``.menu-item`` contendo ``.menu-item-name`` (prato
principal) e ``.menu-item-description`` (acompanhamentos + "Observações:").
Req 1.2, 1.3, 1.4.
"""

from __future__ import annotations

from datetime import date

from notificacoes_ru.coleta.coletor_publico import (
    ColetorPublico,
    ErroColeta,
    parsear_dia,
)
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, ItemCardapio
from notificacoes_ru.nucleo.resultados import Falha, Sucesso, Vazio
from notificacoes_ru.nucleo.texto import contem
from notificacoes_ru.nucleo.tipos import Refeicao


# --------------------------------------------------------------------------
# Dublês de teste
# --------------------------------------------------------------------------
class ClienteFixo:
    """Cliente HTTP que devolve o mesmo HTML para qualquer dia (offline)."""

    def __init__(self, html: str) -> None:
        self._html = html
        self.chamadas: list[tuple[str, int]] = []

    def get_html(self, url: str, timeout: int) -> str:
        self.chamadas.append((url, timeout))
        return self._html


class ClienteFalho:
    """Cliente HTTP que sempre falha, simulando indisponibilidade/timeout."""

    def __init__(self, motivo: str = "timeout") -> None:
        self._motivo = motivo

    def get_html(self, url: str, timeout: int) -> str:
        raise ErroColeta(self._motivo)


class HistoricoFalso:
    """Captura chamadas a ``salvar`` para verificar a integração (Req 1.3)."""

    def __init__(self) -> None:
        self.salvos: list[tuple[Cardapio_Semanal, date, str]] = []

    def salvar(self, cardapio, data_coleta, restaurante) -> None:
        self.salvos.append((cardapio, data_coleta, restaurante))

    # Métodos restantes do contrato não são exercidos aqui.
    def buscar_por_intervalo(self, data_inicial, data_final):  # pragma: no cover
        return []

    def buscar_por_prato(self, termo, data_inicial, data_final):  # pragma: no cover
        return []

    def ranking_mais_servidos(self, data_inicial, data_final, limite=20):  # pragma: no cover
        return []


# --------------------------------------------------------------------------
# Amostras de HTML (estrutura REAL)
# --------------------------------------------------------------------------
# Um dia completo: Almoço, Almoço Vegano, Jantar e Jantar Vegano. O almoço traz
# "SOBRECOXA DE FRANGO" como prato principal (usado no teste de detecção).
HTML_DIA_COMPLETO = """
<!DOCTYPE html>
<html lang="pt-br">
<head><meta charset="iso-8859-1"><title>Cardápio 07/11</title></head>
<body>
  <nav>
    <a href="?d=2026-11-02">Segunda</a>
    <a href="?d=2026-11-07">Sábado</a>
  </nav>
  <main>
    <section class="menu-section">
      <h2 class="menu-section-title">Almoço</h2>
      <div class="menu-item">
        <div class="menu-item-name">SOBRECOXA DE FRANGO</div>
        <div class="menu-item-description">
          Arroz branco<br>
          Feijão carioca<br>
          Salada de alface<br>
          Suco de laranja<br>
          Observações: Contém glúten. Servido das 11h às 14h.
        </div>
      </div>
    </section>
    <section class="menu-section">
      <h2 class="menu-section-title">Almoço Vegano</h2>
      <div class="menu-item">
        <div class="menu-item-name">PROTEÍNA DE SOJA REFOGADA</div>
        <div class="menu-item-description">
          Arroz integral<br>
          Observações: Sem alérgenos conhecidos.
        </div>
      </div>
    </section>
    <section class="menu-section">
      <h2 class="menu-section-title">Jantar</h2>
      <div class="menu-item">
        <div class="menu-item-name">OMELETE DE LEGUMES</div>
        <div class="menu-item-description">
          Arroz branco<br>
          Observações: Contém ovo.
        </div>
      </div>
    </section>
    <section class="menu-section">
      <h2 class="menu-section-title">Jantar Vegano</h2>
      <div class="menu-item">
        <div class="menu-item-name">GRÃO-DE-BICO AO CURRY</div>
        <div class="menu-item-description">
          Arroz branco<br>
          Observações: Pode conter traços de amendoim.
        </div>
      </div>
    </section>
    <p>As refeições serão servidas no RS.</p>
  </main>
</body>
</html>
"""

# Página estruturalmente válida (tem menu-section-title) mas sem menu-item-name
# com conteúdo -> nenhum item de comida.
HTML_SEM_ITENS = """
<html><body>
  <section class="menu-section">
    <h2 class="menu-section-title">Almoço</h2>
  </section>
</body></html>
"""

# Página que não é o cardápio (nenhum menu-section-title) -> EstruturaInvalida.
HTML_ESTRUTURA_INVALIDA = """
<html><body><div class="noticias"><p>Nada por aqui</p></div></body></html>
"""


# --------------------------------------------------------------------------
# Parser (estrutura real)
# --------------------------------------------------------------------------
def test_parser_extrai_pratos_e_mapeia_refeicoes():
    itens = parsear_dia(HTML_DIA_COMPLETO, date(2026, 11, 7))  # sábado

    nomes_principais = {
        item.texto_item
        for item in itens
        if item.texto_item.isupper() or "-" in item.texto_item
    }
    assert "SOBRECOXA DE FRANGO" in nomes_principais
    assert "PROTEÍNA DE SOJA REFOGADA" in nomes_principais
    assert "OMELETE DE LEGUMES" in nomes_principais
    assert "GRÃO-DE-BICO AO CURRY" in nomes_principais

    # Almoço e Almoço Vegano -> ALMOCO; Jantar e Jantar Vegano -> JANTAR.
    por_nome = {item.texto_item: item for item in itens}
    assert por_nome["SOBRECOXA DE FRANGO"].refeicao is Refeicao.ALMOCO
    assert por_nome["PROTEÍNA DE SOJA REFOGADA"].refeicao is Refeicao.ALMOCO
    assert por_nome["OMELETE DE LEGUMES"].refeicao is Refeicao.JANTAR
    assert por_nome["GRÃO-DE-BICO AO CURRY"].refeicao is Refeicao.JANTAR

    # dia_semana derivado da data (2026-11-07 é sábado).
    assert por_nome["SOBRECOXA DE FRANGO"].dia_semana == "sabado"


def test_parser_inclui_acompanhamentos_mas_para_antes_de_observacoes():
    itens = parsear_dia(HTML_DIA_COMPLETO, date(2026, 11, 7))
    textos = [item.texto_item for item in itens]

    # Acompanhamentos antes de "Observações:" entram como itens.
    assert "Arroz branco" in textos
    assert "Suco de laranja" in textos

    # Nada do bloco de observações (alérgenos/horários) vira item de comida.
    assert not any("Observações" in t for t in textos)
    assert not any(contem(t, "contém glúten") for t in textos)
    assert not any(contem(t, "servido das") for t in textos)


def test_parser_sem_secoes_levanta_estrutura_invalida():
    from notificacoes_ru.coleta.coletor_publico import EstruturaInvalida

    try:
        parsear_dia(HTML_ESTRUTURA_INVALIDA, date(2026, 11, 7))
    except EstruturaInvalida:
        pass
    else:  # pragma: no cover
        raise AssertionError("esperava EstruturaInvalida")


# --------------------------------------------------------------------------
# Detecção de "sobrecoxa" (integra com nucleo.texto.contem)
# --------------------------------------------------------------------------
def test_prato_principal_e_encontravel_por_sobrecoxa():
    itens = parsear_dia(HTML_DIA_COMPLETO, date(2026, 11, 7))

    casados = [item for item in itens if contem(item.texto_item, "sobrecoxa")]
    assert casados, "esperava encontrar um item de cardápio contendo 'sobrecoxa'"
    assert casados[0].texto_item == "SOBRECOXA DE FRANGO"
    assert casados[0].refeicao is Refeicao.ALMOCO

    # Também funciona para um ItemCardapio construído diretamente.
    item = ItemCardapio("sabado", Refeicao.ALMOCO, "SOBRECOXA DE FRANGO ASSADA")
    assert contem(item.texto_item, "sobrecoxa")
    assert contem(item.texto_item, "Sobrecoxa")  # insensível a caixa/acento


# --------------------------------------------------------------------------
# Sucesso (Req 1.2, 1.3)
# --------------------------------------------------------------------------
def test_coleta_com_itens_retorna_sucesso_e_persiste():
    historico = HistoricoFalso()
    coletor = ColetorPublico(historico, cliente=ClienteFixo(HTML_DIA_COMPLETO))

    resultado = coletor.coletar("RU")

    assert isinstance(resultado, Sucesso)
    cardapio = resultado.cardapio
    assert cardapio.restaurante == "RU"
    assert cardapio.itens, "esperava itens agregados da semana"

    textos = {item.texto_item for item in cardapio.itens}
    assert "SOBRECOXA DE FRANGO" in textos

    refeicoes = {item.refeicao for item in cardapio.itens}
    assert Refeicao.ALMOCO in refeicoes
    assert Refeicao.JANTAR in refeicoes

    # semana_ano derivado da data de coleta.
    assert cardapio.semana_ano == cardapio.data_coleta.isocalendar().week

    # Persistido exatamente uma vez com os argumentos corretos (Req 1.3).
    assert len(historico.salvos) == 1
    salvo_cardapio, salvo_data, salvo_restaurante = historico.salvos[0]
    assert salvo_restaurante == "RU"
    assert salvo_data == cardapio.data_coleta
    assert salvo_cardapio is cardapio


def test_coleta_busca_a_semana_via_querystring_iso_com_timeout_120():
    cliente = ClienteFixo(HTML_DIA_COMPLETO)
    coletor = ColetorPublico(cliente=cliente)

    coletor.coletar("RA")

    # Uma requisição por dia da semana (segunda..domingo).
    assert len(cliente.chamadas) == 7
    for url, timeout in cliente.chamadas:
        assert timeout == 120
        assert "?d=" in url
        # querystring ISO YYYY-MM-DD
        valor = url.split("?d=", 1)[1]
        assert len(valor) == len("2026-11-07")
        assert valor[4] == "-" and valor[7] == "-"


def test_sucesso_sem_historico_nao_quebra():
    coletor = ColetorPublico(cliente=ClienteFixo(HTML_DIA_COMPLETO))
    resultado = coletor.coletar("RU")
    assert isinstance(resultado, Sucesso)


# --------------------------------------------------------------------------
# Vazio (Req 1.4) — não persiste
# --------------------------------------------------------------------------
def test_cardapio_sem_itens_retorna_vazio_e_nao_persiste():
    historico = HistoricoFalso()
    coletor = ColetorPublico(historico, cliente=ClienteFixo(HTML_SEM_ITENS))

    resultado = coletor.coletar("RU")

    assert isinstance(resultado, Vazio)
    assert historico.salvos == []


# --------------------------------------------------------------------------
# Falha (Req 1.5 / 3.6) — não persiste
# --------------------------------------------------------------------------
def test_falha_de_rede_retorna_falha_e_nao_persiste():
    historico = HistoricoFalso()
    coletor = ColetorPublico(historico, cliente=ClienteFalho("connection timed out"))

    resultado = coletor.coletar("RU")

    assert isinstance(resultado, Falha)
    assert "connection timed out" in resultado.motivo
    assert historico.salvos == []


def test_estrutura_invalida_retorna_falha_e_nao_persiste():
    historico = HistoricoFalso()
    coletor = ColetorPublico(historico, cliente=ClienteFixo(HTML_ESTRUTURA_INVALIDA))

    resultado = coletor.coletar("RU")

    assert isinstance(resultado, Falha)
    assert "estrutura inválida" in resultado.motivo
    assert historico.salvos == []


# --------------------------------------------------------------------------
# Conformidade de contrato
# --------------------------------------------------------------------------
def test_coletor_publico_satisfaz_protocolo_coletor():
    from notificacoes_ru.nucleo.contratos import Coletor

    coletor = ColetorPublico(cliente=ClienteFixo(HTML_DIA_COMPLETO))
    assert isinstance(coletor, Coletor)

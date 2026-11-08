"""Testes do modo robô (``robo.py``) — foco na garantia de NUNCA dia passado.

Cobrem offline (sem rede, sem envio real) a regra que o usuário pediu para
certificar: nem o resumo nem o lembrete podem considerar um dia que já passou.

* ``_coletar_itens(..., nao_antes=hoje)`` descarta datas anteriores a hoje.
* ``modo_resumo`` olha a PRÓXIMA semana (segunda→domingo seguinte), nunca o
  passado, e não envia quando não há ocorrência futura.
* ``modo_lembrete`` coleta apenas o dia de hoje.

A rede é substituída por um ``ClienteRequests`` falso via ``monkeypatch``; o
envio de e-mail é evitado garantindo que não há credenciais SMTP no ambiente
(ou verificando apenas as datas coletadas).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import robo
from notificacoes_ru.nucleo.tipos import Refeicao


class ClienteFalsoPorData:
    """Cliente HTTP falso: devolve HTML com o prato só nas datas configuradas.

    Registra quais datas foram efetivamente requisitadas, para os testes
    verificarem que dias passados NUNCA são buscados.
    """

    def __init__(self, datas_com_prato: set[date]) -> None:
        self._datas_com_prato = datas_com_prato
        self.datas_requisitadas: list[date] = []

    def get_html(self, url: str, timeout: int) -> str:
        # Extrai a data do ?d=YYYY-MM-DD da URL.
        iso = url.split("?d=", 1)[1] if "?d=" in url else url.split("&d=", 1)[1]
        d = date.fromisoformat(iso)
        self.datas_requisitadas.append(d)
        if d in self._datas_com_prato:
            return _html_com_sobrecoxa()
        return _html_sem_prato()


def _html_com_sobrecoxa() -> str:
    return """
    <section class="menu-section">
      <h2 class="menu-section-title">Almoço</h2>
      <div class="menu-item"><div class="menu-item-name">SOBRECOXA DE FRANGO</div></div>
    </section>
    """


def _html_sem_prato() -> str:
    return """
    <section class="menu-section">
      <h2 class="menu-section-title">Almoço</h2>
      <div class="menu-item"><div class="menu-item-name">ARROZ E FEIJAO</div></div>
    </section>
    """


@pytest.fixture()
def config() -> dict:
    return {
        "email_destino": "teste@exemplo.com",
        "pratos": ["sobrecoxa"],
        "restaurante": "RU",
    }


@pytest.fixture(autouse=True)
def _sem_smtp(monkeypatch):
    """Garante que não há credenciais SMTP → nenhum e-mail real é enviado."""
    for var in ("BUSCA_SMTP_USER", "BUSCA_SMTP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# _coletar_itens — filtro nao_antes
# ---------------------------------------------------------------------------
def test_coletar_itens_descarta_datas_passadas(monkeypatch):
    hoje = date(2026, 11, 8)
    ontem = hoje - timedelta(days=1)
    amanha = hoje + timedelta(days=1)

    cliente = ClienteFalsoPorData({ontem, hoje, amanha})
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    robo._coletar_itens([ontem, hoje, amanha], nao_antes=hoje)

    # Ontem NÃO pode ter sido requisitado; hoje e amanhã sim.
    assert ontem not in cliente.datas_requisitadas
    assert hoje in cliente.datas_requisitadas
    assert amanha in cliente.datas_requisitadas


# ---------------------------------------------------------------------------
# modo_resumo — próxima semana, nunca passado
# ---------------------------------------------------------------------------
def test_resumo_olha_proxima_semana_e_nunca_passado(monkeypatch, config):
    # Domingo 08/11/2026. Próxima semana ISO = 09/11 (seg) a 15/11 (dom).
    hoje = date(2026, 11, 8)
    # Coloca o prato num dia JÁ PASSADO (sexta 06) e num dia FUTURO (quarta 11).
    cliente = ClienteFalsoPorData({date(2026, 11, 6), date(2026, 11, 11)})
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    robo.modo_resumo(config, hoje)

    # Só dias da próxima semana (>= 09/11) foram requisitados; nada antes.
    assert all(d >= date(2026, 11, 9) for d in cliente.datas_requisitadas)
    assert date(2026, 11, 6) not in cliente.datas_requisitadas
    # A quarta futura (11) entrou no escopo coletado.
    assert date(2026, 11, 11) in cliente.datas_requisitadas


def test_resumo_sem_credenciais_nao_quebra(monkeypatch, config):
    # Mesmo achando o prato na próxima semana, sem SMTP ele apenas reporta erro
    # de credencial (não lança exceção) — o importante aqui é não quebrar.
    hoje = date(2026, 11, 8)
    cliente = ClienteFalsoPorData({date(2026, 11, 11)})
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    codigo = robo.modo_resumo(config, hoje)
    # Retorna 1 (credencial ausente) sem explodir.
    assert codigo in (0, 1)


# ---------------------------------------------------------------------------
# modo_lembrete — apenas hoje
# ---------------------------------------------------------------------------
def test_lembrete_coleta_apenas_hoje(monkeypatch, config):
    hoje = date(2026, 11, 11)
    cliente = ClienteFalsoPorData({hoje})
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    robo.modo_lembrete(config, hoje)

    # Só o próprio dia foi requisitado.
    assert cliente.datas_requisitadas == [hoje]


def test_lembrete_dia_sem_prato_nao_requisita_passado(monkeypatch, config):
    hoje = date(2026, 11, 10)
    cliente = ClienteFalsoPorData(set())  # nenhum dia tem o prato
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    robo.modo_lembrete(config, hoje)

    assert cliente.datas_requisitadas == [hoje]
    assert all(d >= hoje for d in cliente.datas_requisitadas)


# ---------------------------------------------------------------------------
# Resumo envia SEMPRE (confirmação semanal, mesmo sem sobrecoxa)
# ---------------------------------------------------------------------------
class NotificadorFalso:
    """Captura as chamadas de notificação em vez de enviar e-mail real."""

    def __init__(self) -> None:
        self.ocorrencias = []
        self.mensagens = []

    def notificar_ocorrencias(self, mapa, canal=None, contato=None):
        self.ocorrencias.append(mapa)
        return _ResultadoOk()

    def enviar_mensagem(self, mensagem, canal=None, contato=None):
        self.mensagens.append(mensagem)
        return _ResultadoOk()


class _ResultadoOk:
    entregue = True
    falhas: list = []


def test_resumo_sem_sobrecoxa_envia_aviso_de_confirmacao(monkeypatch, config):
    """Sem ocorrência na próxima semana, o resumo AINDA envia um aviso."""
    hoje = date(2026, 11, 8)
    cliente = ClienteFalsoPorData(set())  # nenhuma sobrecoxa na próxima semana
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    notif = NotificadorFalso()
    monkeypatch.setattr(robo, "_montar_notificador", lambda: notif)

    codigo = robo.modo_resumo(config, hoje)

    assert codigo == 0
    # Enviou a mensagem de confirmação (não a de ocorrências).
    assert notif.ocorrencias == []
    assert len(notif.mensagens) == 1
    corpo = notif.mensagens[0]
    assert "NAAAAAAAAAAAAAAAAAAAO, sobrou nada" in corpo


def test_resumo_com_sobrecoxa_envia_ocorrencias(monkeypatch, config):
    """Com ocorrência na próxima semana, o resumo envia a lista de dias."""
    hoje = date(2026, 11, 8)
    cliente = ClienteFalsoPorData({date(2026, 11, 11)})  # quarta da próxima semana
    monkeypatch.setattr(robo, "ClienteRequests", lambda: cliente)

    notif = NotificadorFalso()
    monkeypatch.setattr(robo, "_montar_notificador", lambda: notif)

    codigo = robo.modo_resumo(config, hoje)

    assert codigo == 0
    # Enviou as ocorrências (não a mensagem de "nenhum").
    assert len(notif.ocorrencias) == 1
    assert notif.mensagens == []

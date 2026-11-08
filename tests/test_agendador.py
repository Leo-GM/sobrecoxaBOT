"""Testes de exemplo do ``Agendador`` (Tarefa 10.1).

Cobrem a orquestração do ciclo semanal e a política de retry de coleta sem
iniciar um scheduler real nem aguardar tempo real: o scheduler do APScheduler é
substituído por um duble que apenas captura o job registrado e o backoff de
30 min é uma função ``dormir`` injetada que não dorme (apenas registra).

Requirements cobertos: 1.1, 1.5, 1.6, 1.7, 4.1, 4.4.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from notificacoes_ru.agendamento import Agendador
from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    ItemCardapio,
    Ocorrencia,
    Prato_Monitorado,
)
from notificacoes_ru.nucleo.resultados import Falha, ResultadoColeta, Sucesso, Vazio
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
    Refeicao,
)


# ---------------------------------------------------------------------------
# Dubles de teste (offline e determinísticos)
# ---------------------------------------------------------------------------
class SchedulerFalso:
    """Captura os jobs registrados sem iniciar o APScheduler real."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.running = False

    def add_job(self, func, trigger=None, id=None, replace_existing=False):  # noqa: A002
        self.jobs.append(
            {
                "func": func,
                "trigger": trigger,
                "id": id,
                "replace_existing": replace_existing,
            }
        )

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


class ColetorSequencia:
    """Coletor que devolve resultados pré-programados por chamada."""

    def __init__(self, resultados: Sequence[ResultadoColeta]) -> None:
        self._resultados = list(resultados)
        self.chamadas: list[str] = []

    def coletar(self, restaurante: str) -> ResultadoColeta:
        self.chamadas.append(restaurante)
        indice = min(len(self.chamadas) - 1, len(self._resultados) - 1)
        return self._resultados[indice]


class DetectorEspiao:
    """Detector que devolve um mapa fixo e registra as chamadas."""

    def __init__(self, resultado) -> None:
        self._resultado = resultado
        self.chamadas: list = []

    def detectar(self, cardapio, pratos):
        self.chamadas.append((cardapio, pratos))
        return self._resultado


class NotificadorEspiao:
    """Notificador que apenas registra qual método foi chamado."""

    def __init__(self) -> None:
        self.ocorrencias: list = []
        self.sem_ocorrencias = 0
        self.falha_coleta = 0
        self.lembretes: list = []

    def notificar_ocorrencias(self, ocorrencias, canal=None, contato=None):
        self.ocorrencias.append(ocorrencias)

    def notificar_sem_ocorrencias(self, canal=None, contato=None):
        self.sem_ocorrencias += 1

    def notificar_falha_coleta(self, canal=None, contato=None):
        self.falha_coleta += 1

    def notificar_lembrete_dia(self, prato_nome, refeicoes, canal=None, contato=None):
        self.lembretes.append((prato_nome, list(refeicoes), canal, contato))


class ConfigFalso:
    """``ConfigRepo`` mínimo em memória para os testes."""

    def __init__(self, horario, pratos, canal, contato) -> None:
        self._horario = horario
        self._pratos = pratos
        self._canal = canal
        self._contato = contato

    def horario_coleta(self):
        return self._horario

    def pratos_monitorados(self):
        return self._pratos

    def canal_e_contato(self):
        return (self._canal, self._contato)


def _cardapio_exemplo() -> Cardapio_Semanal:
    return Cardapio_Semanal(
        restaurante="RU",
        data_coleta=date(2024, 1, 1),
        semana_ano=1,
        itens=(
            ItemCardapio("segunda", Refeicao.ALMOCO, "Sobrecoxa de frango assada"),
        ),
    )


def _config_padrao(horario=None) -> ConfigFalso:
    return ConfigFalso(
        horario=horario or HorarioColeta(hora=7, minuto=0),
        pratos=[Prato_Monitorado("sobrecoxa", "sobrecoxa")],
        canal=Canal_de_Notificacao.EMAIL,
        contato=Dado_de_Contato(Canal_de_Notificacao.EMAIL, "aluno@unicamp.br"),
    )


def _registros_dormir() -> tuple[list, object]:
    esperas: list[float] = []
    return esperas, esperas.append


# ---------------------------------------------------------------------------
# Agendamento (Req 1.1, 1.7)
# ---------------------------------------------------------------------------
def test_agendar_registra_job_cron_no_horario_configurado():
    scheduler = SchedulerFalso()
    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao({}),
        notificador=NotificadorEspiao(),
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    executou = {"n": 0}

    def acao():
        executou["n"] += 1

    agendador.agendar(HorarioColeta(hora=7, minuto=0), acao)

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["id"] == "coleta_semanal"
    assert job["replace_existing"] is True
    # Dispara a ação capturada para confirmar que é a função agendada.
    job["func"]()
    assert executou["n"] == 1


def test_agendar_coleta_usa_horario_do_config():
    scheduler = SchedulerFalso()
    horario = HorarioColeta(hora=9, minuto=30, dia_semana="quarta")
    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao({}),
        notificador=NotificadorEspiao(),
        config=_config_padrao(horario),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    agendador.agendar_coleta()

    assert len(scheduler.jobs) == 1
    # A ação agendada é o ciclo semanal.
    assert scheduler.jobs[0]["func"] == agendador.executar_ciclo_semanal


# ---------------------------------------------------------------------------
# Ciclo semanal: sucesso com ocorrências (Req 4.1)
# ---------------------------------------------------------------------------
def test_ciclo_com_ocorrencias_notifica_ocorrencias():
    cardapio = _cardapio_exemplo()
    prato = Prato_Monitorado("sobrecoxa", "sobrecoxa")
    mapa = {prato: [object()]}
    notificador = NotificadorEspiao()
    detector = DetectorEspiao(mapa)

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(cardapio)]),
        detector=detector,
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=SchedulerFalso(),
    )

    agendador.executar_ciclo_semanal()

    assert notificador.ocorrencias == [mapa]
    assert notificador.sem_ocorrencias == 0
    assert notificador.falha_coleta == 0
    assert detector.chamadas[0][0] is cardapio


# ---------------------------------------------------------------------------
# Ciclo semanal: sucesso sem ocorrências (Req 4.4)
# ---------------------------------------------------------------------------
def test_ciclo_sem_ocorrencias_notifica_sem_ocorrencias():
    prato = Prato_Monitorado("sobrecoxa", "sobrecoxa")
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao({prato: []}),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=SchedulerFalso(),
    )

    agendador.executar_ciclo_semanal()

    assert notificador.sem_ocorrencias == 1
    assert notificador.ocorrencias == []
    assert notificador.falha_coleta == 0


# ---------------------------------------------------------------------------
# Retry de coleta: exatamente 4 tentativas a 30 min (Req 1.5, 1.6)
# ---------------------------------------------------------------------------
def test_retry_coleta_quatro_tentativas_e_notifica_indisponibilidade():
    esperas, dormir = _registros_dormir()
    coletor = ColetorSequencia([Falha("site fora do ar")])
    notificador = NotificadorEspiao()
    detector = DetectorEspiao({})

    agendador = Agendador(
        coletor=coletor,
        detector=detector,
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=SchedulerFalso(),
        dormir=dormir,
    )

    agendador.executar_ciclo_semanal()

    # 1 inicial + 3 adicionais = 4 tentativas (Req 1.5).
    assert len(coletor.chamadas) == 4
    # 3 esperas de 30 minutos entre as tentativas.
    assert esperas == [30 * 60, 30 * 60, 30 * 60]
    # Notifica indisponibilidade e NÃO chama o detector (Req 1.6).
    assert notificador.falha_coleta == 1
    assert detector.chamadas == []


def test_retry_coleta_para_ao_primeiro_sucesso():
    esperas, dormir = _registros_dormir()
    # Falha, falha, depois sucesso: deve parar na 3a tentativa.
    coletor = ColetorSequencia(
        [Falha("timeout"), Falha("timeout"), Sucesso(_cardapio_exemplo())]
    )
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=coletor,
        detector=DetectorEspiao({}),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=SchedulerFalso(),
        dormir=dormir,
    )

    agendador.executar_ciclo_semanal()

    assert len(coletor.chamadas) == 3
    assert len(esperas) == 2
    assert notificador.falha_coleta == 0


def test_cardapio_vazio_tratado_como_falha_de_coleta():
    # Vazio não é Sucesso: após 4 tentativas, notifica indisponibilidade.
    esperas, dormir = _registros_dormir()
    coletor = ColetorSequencia([Vazio()])
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=coletor,
        detector=DetectorEspiao({}),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=SchedulerFalso(),
        dormir=dormir,
    )

    agendador.executar_ciclo_semanal()

    assert len(coletor.chamadas) == 4
    assert notificador.falha_coleta == 1


def test_ciclo_percorre_todos_os_restaurantes():
    notificador = NotificadorEspiao()
    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao({Prato_Monitorado("x", "x"): [object()]}),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU", "RA", "RS"],
        scheduler=SchedulerFalso(),
    )

    agendador.executar_ciclo_semanal()

    assert len(notificador.ocorrencias) == 3


# ---------------------------------------------------------------------------
# Lembretes diários às 10h (Opção 1)
# ---------------------------------------------------------------------------
# 2024-01-01 é uma segunda-feira: toda a semana cai em datas >= data_coleta.
_DATA_COLETA = date(2024, 1, 1)


def _ocorrencia(dia: str, refeicao: Refeicao) -> Ocorrencia:
    return Ocorrencia(
        dia_semana=dia,
        refeicao=refeicao,
        restaurante="RU",
        data_coleta=_DATA_COLETA,
    )


def _jobs_lembrete(scheduler: SchedulerFalso) -> list[dict]:
    return [j for j in scheduler.jobs if str(j["id"]).startswith("lembrete_")]


def test_lembretes_agendados_para_cada_dia_com_ocorrencia():
    scheduler = SchedulerFalso()
    prato = Prato_Monitorado("Sobrecoxa", "sobrecoxa")
    # Mesmo prato em dois dias distintos (segunda e quarta).
    mapa = {
        prato: [
            _ocorrencia("segunda", Refeicao.ALMOCO),
            _ocorrencia("quarta", Refeicao.JANTAR),
        ]
    }
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao(mapa),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    agendador.executar_ciclo_semanal()

    lembretes = _jobs_lembrete(scheduler)
    # Dois dias distintos → dois jobs de lembrete, além do job de coleta.
    assert len(lembretes) == 2
    ids = {j["id"] for j in lembretes}
    assert ids == {
        "lembrete_2024-01-01_Sobrecoxa",  # segunda
        "lembrete_2024-01-03_Sobrecoxa",  # quarta
    }
    for job in lembretes:
        assert job["replace_existing"] is True

    # Disparar a função agendada chama notificar_lembrete_dia.
    lembretes[0]["func"]()
    assert len(notificador.lembretes) == 1
    prato_nome, refeicoes, _, _ = notificador.lembretes[0]
    assert prato_nome == "Sobrecoxa"
    assert refeicoes  # ao menos um período


def test_lembrete_unico_para_prato_no_almoco_e_jantar_do_mesmo_dia():
    scheduler = SchedulerFalso()
    prato = Prato_Monitorado("Sobrecoxa", "sobrecoxa")
    mapa = {
        prato: [
            _ocorrencia("segunda", Refeicao.ALMOCO),
            _ocorrencia("segunda", Refeicao.JANTAR),
        ]
    }
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao(mapa),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    agendador.executar_ciclo_semanal()

    lembretes = _jobs_lembrete(scheduler)
    # Um único lembrete no dia, listando os dois períodos.
    assert len(lembretes) == 1
    lembretes[0]["func"]()
    _, refeicoes, _, _ = notificador.lembretes[0]
    assert Refeicao.ALMOCO.value in refeicoes
    assert Refeicao.JANTAR.value in refeicoes


def test_resumo_semanal_continua_sendo_enviado_com_lembretes():
    scheduler = SchedulerFalso()
    prato = Prato_Monitorado("Sobrecoxa", "sobrecoxa")
    mapa = {prato: [_ocorrencia("segunda", Refeicao.ALMOCO)]}
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao(mapa),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    agendador.executar_ciclo_semanal()

    # O resumo semanal (notificar_ocorrencias) continua sendo enviado.
    assert notificador.ocorrencias == [mapa]
    # E os lembretes foram agendados além dele.
    assert len(_jobs_lembrete(scheduler)) == 1


def test_lembrete_nao_agendado_para_dia_que_ja_passou():
    scheduler = SchedulerFalso()
    prato = Prato_Monitorado("Sobrecoxa", "sobrecoxa")
    # Coleta numa quarta (2024-01-03); ocorrência na segunda já passou.
    mapa = {
        prato: [
            Ocorrencia("segunda", Refeicao.ALMOCO, "RU", date(2024, 1, 3)),
            Ocorrencia("sexta", Refeicao.ALMOCO, "RU", date(2024, 1, 3)),
        ]
    }
    notificador = NotificadorEspiao()

    agendador = Agendador(
        coletor=ColetorSequencia([Sucesso(_cardapio_exemplo())]),
        detector=DetectorEspiao(mapa),
        notificador=notificador,
        config=_config_padrao(),
        restaurantes=["RU"],
        scheduler=scheduler,
    )

    agendador.executar_ciclo_semanal()

    lembretes = _jobs_lembrete(scheduler)
    # Só a sexta (>= quarta) é agendada; a segunda (já passou) não.
    assert len(lembretes) == 1
    assert lembretes[0]["id"] == "lembrete_2024-01-05_Sobrecoxa"

"""Implementação de ``Agendador`` com APScheduler (Tarefa 10.1).

Implementa o contrato :class:`notificacoes_ru.nucleo.contratos.Agendador`
(seção *Components and Interfaces* e *Fluxo semanal principal* do design)::

    interface Agendador:
        agendar(horario: HorarioColeta, acao: () -> void)
        executarCicloSemanal()
            # chama Coletor para cada restaurante, com retry (30 min, 3 adicionais),
            # depois Detector, depois Notificador

Responsabilidades (Req 1.1, 1.5, 1.6, 1.7):

* **Agendamento cron-like.** ``agendar`` registra um job no APScheduler para
  disparar no ``HorarioColeta`` configurado (dia da semana, hora, minuto, fuso).
  O padrão do design é segunda-feira 07:00 em ``America/Sao_Paulo`` (Req 1.1),
  substituível por um horário configurado pelo Usuario (Req 1.7).
* **Orquestração do ciclo semanal.** ``executar_ciclo_semanal`` coleta o
  cardápio de cada ``Restaurante_Universitario`` com retry (a cada 30 minutos,
  até 3 tentativas adicionais — 4 no total, Req 1.5). Em caso de sucesso,
  detecta os pratos monitorados (Detector) e notifica o Usuario (Notificador):
  ocorrências encontradas (Req 4.1) ou "nenhum prato encontrado" (Req 4.4).
  Se todas as 4 tentativas de coleta de um restaurante falham, o Notificador
  envia a mensagem de indisponibilidade e o último cardápio do Historico é
  preservado — o ``ColetorPublico`` só persiste em caso de sucesso (Req 1.6).

Decisões de projeto desta camada:

* **Fonte do tempo injetável.** O backoff de 30 minutos entre tentativas de
  coleta é aplicado por uma função ``dormir(segundos)`` injetável. Em produção
  usa ``time.sleep``; nos testes é substituída por um relógio falso, tornando o
  ciclo rápido e determinístico, sem espera real nem agendador bloqueante.
* **Scheduler injetável.** O ``BackgroundScheduler`` do APScheduler é o padrão,
  mas pode ser substituído nos testes por um duble que apenas captura o job
  registrado, evitando iniciar qualquer agendador real ou aguardar tempo real.
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from notificacoes_ru.nucleo.contratos import (
    Coletor,
    ConfigRepo,
    Detector,
    Notificador,
)
from notificacoes_ru.nucleo.resultados import ResultadoColeta, Sucesso
from notificacoes_ru.nucleo.tipos import HorarioColeta, Restaurante_Universitario

# Intervalo entre tentativas de coleta: 30 minutos (Req 1.5).
INTERVALO_RETRY_SEGUNDOS: float = 30 * 60

# Número de tentativas adicionais após a primeira falha (Req 1.5):
# 1 tentativa inicial + 3 retries = 4 tentativas no total.
MAX_RETRIES_COLETA: int = 3

# Hora do dia em que os lembretes diários são disparados (Opção 1).
HORA_LEMBRETE: int = 10

# Função de espera entre tentativas (injetável para testes determinísticos).
FuncaoDormir = Callable[[float], None]

# Identificador fixo do job de coleta semanal no APScheduler.
_ID_JOB_COLETA = "coleta_semanal"

# Offset (0..6) de cada dia da semana em português a partir da segunda-feira,
# usado para resolver a data real de uma ``Ocorrencia.dia_semana`` dentro da
# semana ISO da coleta.
_OFFSET_DIA_SEMANA: dict[str, int] = {
    "segunda": 0,
    "segunda-feira": 0,
    "terca": 1,
    "terça": 1,
    "terca-feira": 1,
    "terça-feira": 1,
    "quarta": 2,
    "quarta-feira": 2,
    "quinta": 3,
    "quinta-feira": 3,
    "sexta": 4,
    "sexta-feira": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}

# Mapeia o dia da semana em português (``HorarioColeta.dia_semana``) para a
# abreviação de três letras aceita pelo ``CronTrigger`` do APScheduler.
_DIAS_SEMANA: dict[str, str] = {
    "segunda": "mon",
    "segunda-feira": "mon",
    "terca": "tue",
    "terça": "tue",
    "terca-feira": "tue",
    "terça-feira": "tue",
    "quarta": "wed",
    "quarta-feira": "wed",
    "quinta": "thu",
    "quinta-feira": "thu",
    "sexta": "fri",
    "sexta-feira": "fri",
    "sabado": "sat",
    "sábado": "sat",
    "domingo": "sun",
}


def _dia_da_semana_cron(dia: str) -> str:
    """Converte o dia da semana em português para a abreviação do cron.

    Tolera variações de caixa/acentuação; cai no padrão ``mon`` (segunda-feira,
    Req 1.1) quando o rótulo não é reconhecido.
    """
    return _DIAS_SEMANA.get(dia.strip().lower(), "mon")


def _data_do_dia_na_semana(dia_semana: str, data_coleta: date) -> Optional[date]:
    """Resolve a data real de ``dia_semana`` na semana ISO de ``data_coleta``.

    Calcula a segunda-feira da semana ISO de ``data_coleta`` e soma o offset do
    dia (segunda=0 .. domingo=6). Devolve ``None`` quando o rótulo do dia não é
    reconhecido.
    """
    offset = _OFFSET_DIA_SEMANA.get(dia_semana.strip().lower())
    if offset is None:
        return None
    # ``weekday()`` devolve 0 para segunda-feira — a segunda da semana corrente.
    segunda = data_coleta - timedelta(days=data_coleta.weekday())
    return segunda + timedelta(days=offset)


class Agendador:
    """``Agendador`` concreto sobre APScheduler (satisfaz ``nucleo.Agendador``).

    Compõe o ciclo semanal a partir dos componentes já implementados:
    ``Coletor`` (coleta por restaurante), ``Detector`` (pratos monitorados) e
    ``Notificador`` (envio com retry), lendo as Configuracoes do Usuario pelo
    ``ConfigRepo`` (horário, pratos, canal/contato).

    Parâmetros
    ----------
    coletor:
        Implementação de ``Coletor`` (ex.: ``ColetorPublico``). Persiste o
        cardápio no Historico internamente em caso de sucesso (Req 1.3/1.6).
    detector:
        Implementação de ``Detector`` (ex.: ``DetectorPadrao``).
    notificador:
        Implementação de ``Notificador`` (ex.: ``NotificadorComRetry``).
    config:
        ``ConfigRepo`` para ler horário, pratos monitorados e canal/contato.
    restaurantes:
        Restaurantes_Universitarios a coletar a cada ciclo (Req 1.2).
    scheduler:
        Agendador do APScheduler (por padrão ``BackgroundScheduler``). Injetável
        para manter os testes offline e sem espera real.
    dormir:
        Função de espera entre tentativas de coleta (padrão ``time.sleep``).
    intervalo_retry:
        Segundos entre tentativas de coleta (padrão 30 min — Req 1.5).
    max_retries:
        Tentativas adicionais após a primeira (padrão 3 — Req 1.5).
    """

    def __init__(
        self,
        coletor: Coletor,
        detector: Detector,
        notificador: Notificador,
        config: ConfigRepo,
        restaurantes: Sequence[Restaurante_Universitario],
        *,
        scheduler: Optional[BackgroundScheduler] = None,
        dormir: FuncaoDormir = _time.sleep,
        intervalo_retry: float = INTERVALO_RETRY_SEGUNDOS,
        max_retries: int = MAX_RETRIES_COLETA,
    ) -> None:
        self._coletor = coletor
        self._detector = detector
        self._notificador = notificador
        self._config = config
        self._restaurantes = tuple(restaurantes)
        self._scheduler = scheduler if scheduler is not None else BackgroundScheduler()
        self._dormir = dormir
        self._intervalo_retry = intervalo_retry
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Contrato Agendador: agendamento (Req 1.1, 1.7)
    # ------------------------------------------------------------------
    def agendar(self, horario: HorarioColeta, acao: Callable[[], None]) -> None:
        """Agenda ``acao`` para disparar no ``horario`` configurado (Req 1.1, 1.7).

        Registra um job cron-like no APScheduler que dispara no dia da semana,
        hora, minuto e fuso do ``HorarioColeta``. Re-agendar substitui o job
        anterior (``replace_existing``), de modo que uma mudança de horário pelo
        Usuario (Req 1.7) passa a valer imediatamente.
        """
        gatilho = CronTrigger(
            day_of_week=_dia_da_semana_cron(horario.dia_semana),
            hour=horario.hora,
            minute=horario.minuto,
            timezone=horario.fuso,
        )
        self._scheduler.add_job(
            acao,
            trigger=gatilho,
            id=_ID_JOB_COLETA,
            replace_existing=True,
        )

    def agendar_coleta(self) -> None:
        """Agenda o ciclo semanal no horário atualmente configurado (Req 1.7).

        Conveniência que lê o ``HorarioColeta`` do ``ConfigRepo`` e agenda
        ``executar_ciclo_semanal`` como ação do job.
        """
        self.agendar(self._config.horario_coleta(), self.executar_ciclo_semanal)

    def iniciar(self) -> None:
        """Inicia o scheduler em segundo plano, se ainda não estiver rodando."""
        if not self._scheduler.running:
            self._scheduler.start()

    def encerrar(self, *, aguardar: bool = False) -> None:
        """Encerra o scheduler, liberando os recursos do APScheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=aguardar)

    # ------------------------------------------------------------------
    # Contrato Agendador: orquestração do ciclo (Req 1.5, 1.6)
    # ------------------------------------------------------------------
    def executar_ciclo_semanal(self) -> None:
        """Executa o ciclo semanal: coletar → detectar → notificar.

        Para cada ``Restaurante_Universitario`` configurado:

        1. Coleta com retry (30 min, até 3 adicionais — Req 1.5). O
           ``ColetorPublico`` persiste no Historico apenas em caso de sucesso.
        2. Se todas as 4 tentativas falharem, notifica indisponibilidade
           (Req 1.6) e o último cardápio do Historico permanece intacto.
        3. Em caso de sucesso, detecta os pratos monitorados (Detector) e
           notifica: ocorrências encontradas (Req 4.1) ou "nenhum prato
           encontrado" (Req 4.4).
        """
        canal, contato = self._config.canal_e_contato()
        pratos = self._config.pratos_monitorados()

        for restaurante in self._restaurantes:
            resultado = self._coletar_com_retry(restaurante)

            if not isinstance(resultado, Sucesso):
                # Todas as tentativas falharam (ou cardápio vazio/estrutura
                # inválida): avisa indisponibilidade e preserva o Historico
                # (o Coletor nunca persistiu nada neste ciclo) (Req 1.6).
                self._notificador.notificar_falha_coleta(canal, contato)
                continue

            ocorrencias = self._detector.detectar(resultado.cardapio, pratos)

            # Há ocorrência se algum prato tiver ao menos uma ocorrência.
            houve_ocorrencia = any(
                len(lista) > 0 for lista in ocorrencias.values()
            )
            if houve_ocorrencia:
                self._notificador.notificar_ocorrencias(ocorrencias, canal, contato)
                # Opção 1: além do resumo semanal, agenda um lembrete diário
                # para cada dia em que um prato monitorado será servido.
                self._agendar_lembretes(ocorrencias)
            else:
                self._notificador.notificar_sem_ocorrencias(canal, contato)

    # ------------------------------------------------------------------
    # Agendamento dos lembretes diários (Opção 1)
    # ------------------------------------------------------------------
    def _agendar_lembretes(self, ocorrencias) -> None:
        """Agenda um lembrete por (dia, prato) às ``HORA_LEMBRETE`` (Opção 1).

        Para cada prato monitorado com ocorrências, resolve a data real de cada
        dia dentro da semana ISO da coleta e, para datas que ainda não passaram
        (>= ``data_coleta``), registra um job one-shot (``DateTrigger``) às 10h
        daquele dia. Se o mesmo prato aparece no almoço e no jantar do mesmo dia,
        um único lembrete lista os dois períodos. Um lembrete por prato por dia.
        """
        horario = self._config.horario_coleta()

        for prato, lista in ocorrencias.items():
            if not lista:
                continue

            # Agrupa os períodos (refeições) por data real do dia da semana.
            periodos_por_data: dict[date, list[str]] = {}
            for ocorrencia in lista:
                dia_semana = getattr(ocorrencia, "dia_semana", None)
                data_coleta = getattr(ocorrencia, "data_coleta", None)
                refeicao_obj = getattr(ocorrencia, "refeicao", None)
                if dia_semana is None or data_coleta is None or refeicao_obj is None:
                    # Ocorrência sem os campos esperados: não há como resolver a
                    # data/período, então não agenda lembrete para ela.
                    continue
                data_dia = _data_do_dia_na_semana(dia_semana, data_coleta)
                if data_dia is None or data_dia < data_coleta:
                    # Dia desconhecido ou que já passou: não agenda lembrete.
                    continue
                refeicao = getattr(refeicao_obj, "value", refeicao_obj)
                periodos = periodos_por_data.setdefault(data_dia, [])
                if refeicao not in periodos:
                    periodos.append(refeicao)

            for data_dia, periodos in periodos_por_data.items():
                self._agendar_lembrete_dia(
                    prato_nome=prato.nome_original,
                    refeicoes=periodos,
                    data_dia=data_dia,
                    horario=horario,
                )

    def _agendar_lembrete_dia(
        self,
        *,
        prato_nome: str,
        refeicoes: Sequence[str],
        data_dia: date,
        horario: HorarioColeta,
    ) -> None:
        """Registra o job one-shot de lembrete de ``prato_nome`` em ``data_dia``.

        O gatilho é um ``DateTrigger`` às ``HORA_LEMBRETE`` no fuso do
        ``HorarioColeta``. O id é único por dia e prato
        (``lembrete_{data_iso}_{prato}``) com ``replace_existing=True``, de modo
        que reexecuções do ciclo substituam lembretes anteriores sem duplicar.
        """
        quando = datetime(
            data_dia.year,
            data_dia.month,
            data_dia.day,
            HORA_LEMBRETE,
            0,
            tzinfo=ZoneInfo(horario.fuso),
        )
        gatilho = DateTrigger(run_date=quando, timezone=horario.fuso)
        job_id = f"lembrete_{data_dia.isoformat()}_{prato_nome}"
        self._scheduler.add_job(
            self._criar_acao_lembrete(prato_nome, list(refeicoes)),
            trigger=gatilho,
            id=job_id,
            replace_existing=True,
        )

    def _criar_acao_lembrete(
        self,
        prato_nome: str,
        refeicoes: list[str],
    ) -> Callable[[], None]:
        """Cria a ação one-shot que envia o lembrete lendo o contato atual.

        O canal/contato são lidos do ``ConfigRepo`` no momento do disparo (10h do
        dia), não no momento do agendamento, para refletir mudanças de
        configuração feitas depois da coleta.
        """

        def acao() -> None:
            canal, contato = self._config.canal_e_contato()
            self._notificador.notificar_lembrete_dia(
                prato_nome, refeicoes, canal, contato
            )

        return acao

    def _coletar_com_retry(
        self,
        restaurante: Restaurante_Universitario,
    ) -> ResultadoColeta:
        """Coleta o cardápio de ``restaurante`` aplicando a política de retry.

        Faz 1 tentativa inicial + até ``max_retries`` adicionais, aguardando
        ``intervalo_retry`` segundos (padrão 30 min) entre elas (Req 1.5).
        Interrompe assim que uma coleta tem ``Sucesso``; devolve o último
        resultado não-sucesso quando todas as tentativas falham.
        """
        total_tentativas = self._max_retries + 1  # inicial + adicionais
        resultado: ResultadoColeta = self._coletor.coletar(restaurante)

        tentativa = 1
        while not isinstance(resultado, Sucesso) and tentativa < total_tentativas:
            # Backoff de 30 min antes de cada retry (Req 1.5). A espera é
            # delegada à função injetável — em testes, um relógio falso.
            self._dormir(self._intervalo_retry)
            resultado = self._coletor.coletar(restaurante)
            tentativa += 1

        return resultado

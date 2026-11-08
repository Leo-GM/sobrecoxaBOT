"""Camada de agendamento (APScheduler).

Expõe o ``Agendador`` concreto (Tarefa 10.1) que satisfaz o contrato
``notificacoes_ru.nucleo.contratos.Agendador``: agenda a coleta semanal no
horário configurado e orquestra o ciclo coletar → detectar → notificar, com
retry de coleta (30 min, até 3 adicionais).
"""

from notificacoes_ru.agendamento.agendador import (
    INTERVALO_RETRY_SEGUNDOS,
    MAX_RETRIES_COLETA,
    Agendador,
)

__all__ = [
    "Agendador",
    "INTERVALO_RETRY_SEGUNDOS",
    "MAX_RETRIES_COLETA",
]

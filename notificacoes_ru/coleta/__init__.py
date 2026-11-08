"""Camada de coleta (scraping) do Cardapio_Semanal.

Implementações concretas do contrato ``nucleo.Coletor`` — ``ColetorPublico``
(padrão) e ``ColetorAutenticado`` (opcional) — serão adicionadas nas tarefas 6.
"""

from notificacoes_ru.coleta.coletor_publico import (
    ClienteHTTP,
    ClienteRequests,
    ColetorPublico,
    ENCODING_PAGINA,
    ErroColeta,
    EstruturaInvalida,
    TIMEOUT_SEGUNDOS,
    URL_PADRAO,
    parsear_dia,
)

__all__ = [
    "ClienteHTTP",
    "ClienteRequests",
    "ColetorPublico",
    "ENCODING_PAGINA",
    "ErroColeta",
    "EstruturaInvalida",
    "TIMEOUT_SEGUNDOS",
    "URL_PADRAO",
    "parsear_dia",
]

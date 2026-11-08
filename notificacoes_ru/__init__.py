"""Notificações_RU — monitoramento do cardápio dos RUs da Unicamp.

Pacote raiz da aplicação. Os subpacotes seguem as camadas do design:

- ``nucleo``: tipos conceituais e contratos (Protocols/ABCs) compartilhados.
- ``coleta``: coletor(es) de cardápio (scraping).
- ``persistencia``: modelos de dados e repositórios (SQLite).
- ``notificacao``: adaptadores de canal e política de notificação.
- ``agendamento``: agendador do ciclo semanal.
- ``web``: camada web / UI (FastAPI + Jinja2).
"""

__all__ = [
    "nucleo",
    "coleta",
    "persistencia",
    "notificacao",
    "agendamento",
    "web",
]

__version__ = "0.1.0"

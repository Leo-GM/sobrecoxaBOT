"""Camada de notificação.

Adaptadores de canal (``nucleo.CanalNotificacao``) e geração de mensagens
(tarefa 8.1), e a política de notificação com retry e preservação de
ocorrências (``nucleo.Notificador``) da tarefa 8.2.
"""

from notificacoes_ru.notificacao.canais import (
    ADAPTADORES,
    TIMEOUT_ENVIO_SEGUNDOS,
    CanalConcreto,
    NotificadorEmail,
    NotificadorTelegram,
    NotificadorWhatsApp,
    Transporte,
    criar_canal,
)
from notificacoes_ru.notificacao.mensagens import (
    mensagem_falha_coleta,
    mensagem_ocorrencias,
    mensagem_sem_ocorrencias,
    validar_contato,
)
from notificacoes_ru.notificacao.politica import (
    INTERVALO_RETRY_SEGUNDOS,
    MAX_RETRIES,
    NotificadorComRetry,
    RegistroFalha,
    ResultadoNotificacao,
)

__all__ = [
    # adaptadores de canal (8.1)
    "NotificadorWhatsApp",
    "NotificadorTelegram",
    "NotificadorEmail",
    "ADAPTADORES",
    "CanalConcreto",
    "Transporte",
    "TIMEOUT_ENVIO_SEGUNDOS",
    "criar_canal",
    # mensagens e validação (8.1)
    "mensagem_ocorrencias",
    "mensagem_sem_ocorrencias",
    "mensagem_falha_coleta",
    "validar_contato",
    # política de retry e preservação (8.2)
    "NotificadorComRetry",
    "ResultadoNotificacao",
    "RegistroFalha",
    "INTERVALO_RETRY_SEGUNDOS",
    "MAX_RETRIES",
]

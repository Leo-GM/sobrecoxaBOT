"""Camada de segurança.

Expõe o ``CofreCredenciais`` (Tarefa 5.1), responsável por criptografar a
``Credencial_Unicamp`` em repouso (Fernet), decifrá-la sob demanda apenas para
a coleta e garantir que a senha em claro nunca apareça em UI, logs ou
notificações (Req 6.2–6.5, 6.8).
"""

from notificacoes_ru.seguranca.cofre import (
    CARACTERE_MASCARA,
    CofreCredenciaisFernet,
    CredencialAusenteError,
    carregar_ou_criar_chave,
    gerar_chave,
)

__all__ = [
    "CARACTERE_MASCARA",
    "CofreCredenciaisFernet",
    "CredencialAusenteError",
    "carregar_ou_criar_chave",
    "gerar_chave",
]

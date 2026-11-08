"""Ponto de entrada executável do Marimbondos Informes RU (Tarefa 12.1).

Permite iniciar a aplicação completa com::

    python -m notificacoes_ru

Delega todo o *wiring* e a inicialização bloqueante (scheduler + servidor web)
a :func:`notificacoes_ru.composicao.executar`, usando a chave Fernet persistente
padrão para preservar a ``Credencial_Unicamp`` entre reinícios (Req 6.2).
"""

from __future__ import annotations

from notificacoes_ru.composicao import executar


def _carregar_env() -> None:
    """Carrega variáveis do arquivo ``.env`` (credenciais SMTP), se existir.

    O ``.env`` fica na raiz do projeto e guarda as credenciais do Gmail
    (``BUSCA_SMTP_*``) usadas para o envio real das notificações. É opcional:
    se o arquivo ou a biblioteca ``python-dotenv`` não existirem, a aplicação
    segue lendo apenas as variáveis de ambiente já definidas (e, sem elas, cai
    no modo que não envia e-mail).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # ``load_dotenv`` procura o .env a partir do diretório atual para cima;
    # não sobrescreve variáveis já definidas no ambiente.
    load_dotenv(override=False)


def main() -> None:
    """Inicia a aplicação com as configurações padrão."""
    _carregar_env()
    executar()


if __name__ == "__main__":  # pragma: no cover - acionado apenas via linha de comando
    main()

"""Composição de ponta a ponta da aplicação (Tarefa 12.1).

Este módulo é a *composition root* do Marimbondos Informes RU: conecta todas as camadas
já implementadas em uma única aplicação executável, seguindo o
*Fluxo semanal principal* do design (Agendador → Coletor → Historico →
Detector → Notificador) e expondo a camada web (FastAPI).

Componentes conectados:

* **Camada web** (tarefa 11): :func:`notificacoes_ru.web.app.create_app`, que por
  sua vez usa :class:`~notificacoes_ru.web.dependencias.ContextoApp` para montar
  ``ConfigRepoSQLite`` + ``CofreCredenciaisFernet`` + ``HistoricoSQLite`` sobre
  uma única conexão SQLite.
* **Coletor** (tarefa 6): :class:`~notificacoes_ru.coleta.coletor_publico.ColetorPublico`,
  recebendo o ``HistoricoSQLite`` do contexto para persistir em caso de sucesso.
* **Detector** (tarefa 7): :class:`~notificacoes_ru.deteccao.detector.DetectorPadrao`.
* **Notificador** (tarefa 8): :class:`~notificacoes_ru.notificacao.politica.NotificadorComRetry`
  sobre um canal criado por :func:`~notificacoes_ru.notificacao.canais.criar_canal`.
* **Agendador** (tarefa 10): :class:`~notificacoes_ru.agendamento.agendador.Agendador`,
  que orquestra o ciclo semanal e agenda a coleta no horário configurado.
* **Normalizador** (tarefa 2), **persistência** (tarefa 3) e **Cofre** (tarefa 5)
  entram indiretamente: o Normalizador é usado por ``ConfigRepo``/``Detector``,
  os repositórios e o Cofre vivem no ``ContextoApp``.

## Separação entre composição e execução

A composição (:func:`compor_aplicacao`) é **pura em efeitos externos**: constrói
os objetos e faz o *wiring*, mas **não** inicia o scheduler, **não** sobe o
servidor web e **não** faz chamadas de rede. Isso a torna testável com um banco
em memória e um transporte de notificação stub.

A execução bloqueante (iniciar o APScheduler + subir o uvicorn) fica isolada em
:func:`executar`, que só deve ser chamada no ponto de entrada real
(``python -m notificacoes_ru``). Os testes exercitam :func:`compor_aplicacao`,
nunca :func:`executar`.

## Chave Fernet persistente

O ponto de entrada usa :data:`CAMINHO_CHAVE_PADRAO` como fonte **persistente** da
chave Fernet (via ``carregar_ou_criar_chave``), de modo que a ``Credencial_Unicamp``
cifrada no banco continue decifrável entre reinícios do processo (Req 6.2). Uma
chave efêmera só é usada quando nenhuma fonte persistente é informada — adequado
apenas para testes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union

from fastapi import FastAPI

from notificacoes_ru.agendamento.agendador import Agendador
from notificacoes_ru.coleta.coletor_publico import ColetorPublico
from notificacoes_ru.deteccao.detector import DetectorPadrao
from notificacoes_ru.notificacao.canais import (
    CanalConcreto,
    Transporte,
    criar_canal,
)
from notificacoes_ru.notificacao.politica import NotificadorComRetry
from notificacoes_ru.notificacao.transporte_email import (
    transporte_email_do_ambiente,
)
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    Restaurante_Universitario,
)
from notificacoes_ru.persistencia.esquema import CAMINHO_BANCO_PADRAO
from notificacoes_ru.web.app import create_app
from notificacoes_ru.web.dependencias import ContextoApp, construir_contexto

# Caminho persistente padrão da chave Fernet (ao lado do banco). Mantém a chave
# fora do versionamento; é um segredo e não deve ser registrada em log (Req 6.5).
CAMINHO_CHAVE_PADRAO = Path("notificacoes_ru.key")

# Restaurantes_Universitarios monitorados por padrão (Req 1.2). Podem ser
# sobrescritos pelo chamador do ponto de entrada.
RESTAURANTES_PADRAO: tuple[Restaurante_Universitario, ...] = ("RU", "RA", "RS")

# Canal de notificação padrão quando o Usuario ainda não configurou um. O envio
# real só ocorre quando houver canal/contato válidos; o ciclo semanal lê sempre
# o canal/contato atuais do ConfigRepo, então este default apenas inicializa o
# adaptador de transporte.
CANAL_PADRAO = Canal_de_Notificacao.EMAIL

# Host/porta padrão do servidor web.
HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000


def transporte_noop(destino: Dado_de_Contato, mensagem: str, timeout: float) -> None:
    """Transporte de notificação *no-op* (stub) usado por padrão.

    As integrações reais (WhatsApp Cloud/Twilio, Bot API do Telegram, SMTP) estão
    fora do escopo desta composição; por padrão o transporte não envia nada e
    retorna com sucesso. Um transporte real é **injetável** via
    :func:`compor_aplicacao` (parâmetro ``transporte``) sem alterar o restante
    do *wiring*.

    Nunca registra a mensagem em log para não vazar conteúdo sensível (Req 6.5).
    """
    return None


@dataclass
class ComposicaoApp:
    """Resultado do *wiring*: todos os componentes conectados da aplicação.

    Agrupa a aplicação web FastAPI e os objetos de domínio já conectados entre
    si (Coletor → Historico, Detector, Notificador → canal, Agendador). É
    produzida por :func:`compor_aplicacao` e consumida por :func:`executar` (no
    ponto de entrada) ou diretamente pelos testes de integração.

    Atributos
    ---------
    app:
        A aplicação FastAPI pronta (routers de configuração e histórico).
    contexto:
        O ``ContextoApp`` com a conexão SQLite e os repositórios/Cofre.
    coletor:
        ``ColetorPublico`` ligado ao ``HistoricoSQLite`` do contexto.
    detector:
        ``DetectorPadrao``.
    notificador:
        ``NotificadorComRetry`` sobre o canal/transporte configurado.
    agendador:
        ``Agendador`` que orquestra o ciclo semanal e agenda a coleta.
    restaurantes:
        Restaurantes_Universitarios que o ciclo coleta a cada semana.
    """

    app: FastAPI
    contexto: ContextoApp
    coletor: ColetorPublico
    detector: DetectorPadrao
    notificador: NotificadorComRetry
    agendador: Agendador
    canal: CanalConcreto
    restaurantes: tuple[Restaurante_Universitario, ...]


def compor_aplicacao(
    *,
    conexao=None,
    caminho_banco: Union[str, Path, None] = None,
    chave_fernet: bytes | None = None,
    caminho_chave: Union[str, Path, None] = None,
    restaurantes: Sequence[Restaurante_Universitario] = RESTAURANTES_PADRAO,
    transporte: Transporte = transporte_noop,
    canal_padrao: Canal_de_Notificacao = CANAL_PADRAO,
) -> ComposicaoApp:
    """Conecta todos os componentes e devolve a :class:`ComposicaoApp`.

    Esta função faz apenas o *wiring*: constrói o ``ContextoApp`` (que inicializa
    o banco), instancia ``ColetorPublico`` + ``DetectorPadrao`` +
    ``NotificadorComRetry`` + ``Agendador`` e agenda a coleta semanal no horário
    configurado. **Não** inicia o scheduler nem sobe o servidor — isso é
    responsabilidade de :func:`executar`.

    A conexão/banco e a fonte da chave Fernet são repassados a
    :func:`~notificacoes_ru.web.dependencias.construir_contexto`. Para preservar
    a credencial entre reinícios em produção, informe ``caminho_chave`` (fonte
    persistente); em testes, uma ``conexao`` em memória e uma ``chave_fernet``
    efêmera são suficientes.

    Parâmetros
    ----------
    transporte:
        Função de envio efetivo da notificação. Por padrão :func:`transporte_noop`
        (stub); injete um transporte real (WhatsApp/Telegram/SMTP) aqui.
    restaurantes:
        Restaurantes_Universitarios a coletar a cada ciclo (Req 1.2).
    canal_padrao:
        Canal usado para instanciar o adaptador de transporte. O ciclo semanal
        sempre lê o canal/contato atuais do ``ConfigRepo`` ao notificar.
    """
    # 1. Contexto compartilhado: conexão SQLite inicializada + ConfigRepo,
    #    Cofre (chave Fernet) e HistoricoRepo (persistência + cofre + normalizador
    #    entram aqui, reutilizando o wiring da camada web).
    contexto = construir_contexto(
        conexao=conexao,
        caminho_banco=caminho_banco,
        chave_fernet=chave_fernet,
        caminho_chave=caminho_chave,
    )

    # 2. Aplicação web reaproveitando o MESMO contexto (uma única conexão/banco
    #    e uma única chave para web e ciclo semanal) — tarefa 11.
    app = create_app(contexto=contexto)

    # 3. Coletor público ligado ao Historico do contexto (persiste só em sucesso,
    #    Req 1.3) — tarefa 6.
    coletor = ColetorPublico(historico=contexto.historico_repo)

    # 4. Detector — tarefa 7.
    detector = DetectorPadrao()

    # 5. Notificador com retry sobre um canal com transporte injetável — tarefa 8.
    canal = criar_canal(canal_padrao, transporte)
    notificador = NotificadorComRetry(canal)

    # 6. Agendador orquestrando o ciclo semanal (coleta → detecção → notificação)
    #    — tarefa 10.
    restaurantes_tuple = tuple(restaurantes)
    agendador = Agendador(
        coletor=coletor,
        detector=detector,
        notificador=notificador,
        config=contexto.config_repo,
        restaurantes=restaurantes_tuple,
    )

    # 7. Agenda a coleta semanal no horário atualmente configurado (Req 1.1/1.7).
    #    Apenas registra o job; o scheduler só é iniciado em ``executar``.
    agendador.agendar_coleta()

    return ComposicaoApp(
        app=app,
        contexto=contexto,
        coletor=coletor,
        detector=detector,
        notificador=notificador,
        agendador=agendador,
        canal=canal,
        restaurantes=restaurantes_tuple,
    )


def executar(
    *,
    caminho_banco: Union[str, Path, None] = CAMINHO_BANCO_PADRAO,
    caminho_chave: Union[str, Path, None] = CAMINHO_CHAVE_PADRAO,
    restaurantes: Sequence[Restaurante_Universitario] = RESTAURANTES_PADRAO,
    transporte: Transporte | None = None,
    host: str = HOST_PADRAO,
    porta: int = PORTA_PADRAO,
) -> None:
    """Ponto de entrada bloqueante: inicia o scheduler e sobe o servidor web.

    Fluxo:

    0. Resolve o transporte de notificação: se ``transporte`` não for informado,
       tenta montar um transporte SMTP real a partir das variáveis de ambiente
       ``BUSCA_SMTP_*`` (:func:`~notificacoes_ru.notificacao.transporte_email.transporte_email_do_ambiente`);
       se não estiverem configuradas, usa :func:`transporte_noop` (não envia).
    1. Compõe a aplicação (:func:`compor_aplicacao`) com uma fonte **persistente**
       de chave Fernet (``caminho_chave``), para que a credencial cifrada
       sobreviva a reinícios (Req 6.2), e um banco em arquivo (``caminho_banco``).
    2. Inicia o APScheduler em segundo plano (``agendador.iniciar``), ativando o
       job de coleta semanal já agendado.
    3. Sobe o servidor ASGI (uvicorn), que bloqueia o processo até o encerramento.
    4. Ao encerrar, para o scheduler de forma limpa (``agendador.encerrar``).

    Esta função **não** é exercitada pelos testes (eles usam
    :func:`compor_aplicacao`). O ``import`` do uvicorn é feito aqui dentro para
    manter a composição livre de efeitos de inicialização do servidor.
    """
    import uvicorn

    # Sem transporte explícito, tenta configurar o envio real por e-mail a
    # partir das variáveis de ambiente (BUSCA_SMTP_*). Quando não configurado,
    # cai no transporte no-op (comportamento atual). A senha nunca é logada.
    if transporte is None:
        transporte = transporte_email_do_ambiente() or transporte_noop

    composicao = compor_aplicacao(
        caminho_banco=caminho_banco,
        caminho_chave=caminho_chave,
        restaurantes=restaurantes,
        transporte=transporte,
    )

    composicao.agendador.iniciar()
    try:
        uvicorn.run(composicao.app, host=host, port=porta)
    finally:
        composicao.agendador.encerrar()

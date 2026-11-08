"""Testes de integração da composição de ponta a ponta (Tarefa 12.1).

Exercitam o *wiring* de :func:`notificacoes_ru.composicao.compor_aplicacao` sem
iniciar o scheduler real, sem fazer chamadas de rede e sem subir o uvicorn:

* a aplicação FastAPI responde e compartilha o mesmo ``ContextoApp`` (uma única
  conexão SQLite / chave Fernet) com os componentes do ciclo semanal;
* o Agendador agenda o job de coleta semanal (sem iniciar o scheduler);
* o ciclo semanal (coleta → detecção → notificação) funciona de ponta a ponta
  com um Coletor stub e um transporte de notificação stub, persistindo no
  Historico e notificando pelo canal/contato configurados.

Nenhuma dependência externa real é tocada: o Coletor é substituído por um duble
offline e o transporte de notificação é o *no-op* padrão (injetável).
"""

from __future__ import annotations

import sqlite3
from datetime import date

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from notificacoes_ru.composicao import ComposicaoApp, compor_aplicacao
from notificacoes_ru.nucleo.modelos import Cardapio_Semanal, ItemCardapio
from notificacoes_ru.nucleo.resultados import ResultadoColeta, Sucesso
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    Refeicao,
    Restaurante_Universitario,
)


# ---------------------------------------------------------------------------
# Dubles offline e determinísticos
# ---------------------------------------------------------------------------
class ColetorStub:
    """Coletor que devolve um cardápio fixo e persiste no Historico informado."""

    def __init__(self, historico, cardapio: Cardapio_Semanal) -> None:
        self._historico = historico
        self._cardapio = cardapio
        self.chamadas: list[Restaurante_Universitario] = []

    def coletar(self, restaurante: Restaurante_Universitario) -> ResultadoColeta:
        self.chamadas.append(restaurante)
        self._historico.salvar(
            self._cardapio, self._cardapio.data_coleta, restaurante
        )
        return Sucesso(cardapio=self._cardapio)


def _conexao_memoria() -> sqlite3.Connection:
    """Conexão SQLite em memória compartilhável entre threads (como na web)."""
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def _compor_em_memoria(**kwargs) -> ComposicaoApp:
    """Compõe a aplicação sobre SQLite em memória e chave Fernet efêmera."""
    return compor_aplicacao(
        conexao=_conexao_memoria(),
        chave_fernet=Fernet.generate_key(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Wiring: aplicação web + contexto único + job agendado
# ---------------------------------------------------------------------------
def test_composicao_conecta_todos_os_componentes():
    """A composição produz todos os componentes conectados ao mesmo contexto."""
    composicao = _compor_em_memoria(restaurantes=("RU",))

    # Todos os componentes principais foram instanciados.
    assert composicao.app.title == "Marimbondos Informes RU"
    assert composicao.coletor is not None
    assert composicao.detector is not None
    assert composicao.notificador is not None
    assert composicao.agendador is not None

    # Coletor, repositórios e a web compartilham a MESMA conexão/contexto.
    assert composicao.coletor._historico is composicao.contexto.historico_repo
    assert composicao.app.state.contexto is composicao.contexto


def test_composicao_agenda_coleta_sem_iniciar_scheduler():
    """O job de coleta semanal é agendado, mas o scheduler NÃO é iniciado."""
    composicao = _compor_em_memoria()

    jobs = composicao.agendador._scheduler.get_jobs()
    assert [job.id for job in jobs] == ["coleta_semanal"]
    # A composição é não bloqueante: nada de scheduler rodando nem porta aberta.
    assert composicao.agendador._scheduler.running is False


def test_app_web_responde_pela_composicao():
    """A aplicação web composta atende requisições (raiz redireciona)."""
    composicao = _compor_em_memoria()

    with TestClient(composicao.app) as cliente:
        resposta = cliente.get("/", follow_redirects=False)
        assert resposta.status_code == 303
        assert resposta.headers["location"] == "/configuracao"


# ---------------------------------------------------------------------------
# Ciclo semanal de ponta a ponta (coleta → detecção → notificação)
# ---------------------------------------------------------------------------
def test_ciclo_semanal_ponta_a_ponta_notifica_e_persiste():
    """Coleta → detecção → notificação com stubs: persiste e notifica ocorrências."""
    composicao = _compor_em_memoria(restaurantes=("RU",))
    ctx = composicao.contexto

    # Configura um prato monitorado e um canal/contato válidos (via ConfigRepo).
    ctx.config_repo.adicionar_prato("Sobrecoxa de frango")
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="eu@exemplo.com")
    ctx.config_repo.definir_canal(Canal_de_Notificacao.EMAIL, contato)

    # Cardápio contendo o prato monitorado.
    cardapio = Cardapio_Semanal(
        restaurante="RU",
        data_coleta=date(2024, 6, 3),
        semana_ano=date(2024, 6, 3).isocalendar().week,
        itens=(
            ItemCardapio(
                dia_semana="segunda",
                refeicao=Refeicao.ALMOCO,
                texto_item="Sobrecoxa de frango assada",
            ),
        ),
    )

    # Substitui o coletor por um stub offline que persiste no mesmo Historico.
    stub = ColetorStub(ctx.historico_repo, cardapio)
    composicao.agendador._coletor = stub

    # Executa o ciclo diretamente (sem scheduler nem espera real).
    composicao.agendador.executar_ciclo_semanal()

    # O coletor foi chamado para o restaurante configurado.
    assert stub.chamadas == ["RU"]

    # O cardápio foi persistido no Historico (consulta por intervalo).
    armazenados = ctx.historico_repo.buscar_por_intervalo(
        date(2024, 6, 3), date(2024, 6, 3)
    )
    assert len(armazenados) == 1
    assert armazenados[0].restaurante == "RU"

    # A notificação preservou as ocorrências detectadas (Property 11 / Req 4.7)
    # e o envio foi entregue pelo transporte no-op.
    ocorrencias = composicao.notificador.ultimas_ocorrencias()
    assert ocorrencias is not None
    assert any(len(lista) > 0 for lista in ocorrencias.values())


def test_ciclo_semanal_usa_transporte_injetado():
    """O transporte de notificação é injetável e é efetivamente acionado."""
    enviados: list[tuple[str, str]] = []

    def transporte_capturando(destino, mensagem, timeout):
        enviados.append((destino.valor, mensagem))

    composicao = _compor_em_memoria(
        restaurantes=("RU",),
        transporte=transporte_capturando,
    )
    ctx = composicao.contexto

    ctx.config_repo.adicionar_prato("arroz")
    contato = Dado_de_Contato(canal=Canal_de_Notificacao.EMAIL, valor="eu@exemplo.com")
    ctx.config_repo.definir_canal(Canal_de_Notificacao.EMAIL, contato)

    cardapio = Cardapio_Semanal(
        restaurante="RU",
        data_coleta=date(2024, 6, 10),
        semana_ano=date(2024, 6, 10).isocalendar().week,
        itens=(
            ItemCardapio(
                dia_semana="terça",
                refeicao=Refeicao.JANTAR,
                texto_item="Arroz branco",
            ),
        ),
    )
    composicao.agendador._coletor = ColetorStub(ctx.historico_repo, cardapio)

    composicao.agendador.executar_ciclo_semanal()

    # O transporte injetado recebeu exatamente uma mensagem para o contato.
    assert len(enviados) == 1
    destino, mensagem = enviados[0]
    assert destino == "eu@exemplo.com"
    assert mensagem  # mensagem não vazia

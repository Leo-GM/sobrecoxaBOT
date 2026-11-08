"""Contratos conceituais do núcleo (Protocols).

Cada contrato corresponde a uma interface da seção *Components and Interfaces*
do design. São definições estruturais (``typing.Protocol``, ``runtime_checkable``)
SEM implementação — as classes concretas que os satisfazem são criadas nas
tarefas seguintes.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from notificacoes_ru.nucleo.modelos import (
    Cardapio_Semanal,
    Credencial_Unicamp,
    Ocorrencia,
    Prato_Monitorado,
)
from notificacoes_ru.nucleo.resultados import ResultadoColeta, ResultadoEnvio
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
    Restaurante_Universitario,
)


@runtime_checkable
class Coletor(Protocol):
    """Contrato de extração do Cardapio_Semanal (scraping).

    Implementado por ``ColetorPublico`` (padrão) e, opcionalmente, por
    ``ColetorAutenticado``. Ver Req 1.2–1.4, 6.1.
    """

    def coletar(self, restaurante: Restaurante_Universitario) -> ResultadoColeta:
        ...


@runtime_checkable
class Detector(Protocol):
    """Localiza os pratos monitorados no cardápio (Req 3).

    Usa o Normalizador compartilhado; retorna lista vazia por prato sem
    ocorrência e sinaliza erro estruturado para cardápio ausente/vazio/inválido
    preservando o estado anterior (Req 3.5, 3.6).
    """

    def detectar(
        self,
        cardapio: Cardapio_Semanal,
        pratos: Sequence[Prato_Monitorado],
    ) -> Mapping[Prato_Monitorado, Sequence[Ocorrencia]]:
        ...


@runtime_checkable
class CanalNotificacao(Protocol):
    """Adaptador de um canal de envio (WhatsApp/Telegram/e-mail), timeout 30s."""

    def enviar(self, destino: Dado_de_Contato, mensagem: str) -> ResultadoEnvio:
        ...


@runtime_checkable
class Notificador(Protocol):
    """Política de notificação com retry (10 min, 3 adicionais). Ver Req 4."""

    def notificar_ocorrencias(
        self,
        ocorrencias: Mapping[Prato_Monitorado, Sequence[Ocorrencia]],
        canal: Canal_de_Notificacao,
        contato: Dado_de_Contato,
    ) -> None:
        ...

    def notificar_sem_ocorrencias(
        self,
        canal: Canal_de_Notificacao,
        contato: Dado_de_Contato,
    ) -> None:
        ...

    def notificar_falha_coleta(
        self,
        canal: Canal_de_Notificacao,
        contato: Dado_de_Contato,
    ) -> None:
        ...


@runtime_checkable
class HistoricoRepo(Protocol):
    """Repositório do Historico de cardápios (retenção mínima de 12 meses)."""

    def salvar(
        self,
        cardapio: Cardapio_Semanal,
        data_coleta: date,
        restaurante: Restaurante_Universitario,
    ) -> None:
        ...

    def buscar_por_intervalo(
        self,
        data_inicial: date,
        data_final: date,
    ) -> Sequence[Cardapio_Semanal]:
        ...

    def buscar_por_prato(
        self,
        termo: str,
        data_inicial: date,
        data_final: date,
    ) -> Sequence[Ocorrencia]:
        ...

    def ranking_mais_servidos(
        self,
        data_inicial: date,
        data_final: date,
        limite: int = 20,
    ) -> Sequence[tuple[str, int]]:
        ...


@runtime_checkable
class ConfigRepo(Protocol):
    """Repositório das Configuracoes do Usuario (Req 2, 4.3, 1.7)."""

    def pratos_monitorados(self) -> Sequence[Prato_Monitorado]:
        ...

    def adicionar_prato(self, nome: str) -> Prato_Monitorado:
        ...

    def remover_prato(self, nome_normalizado: str) -> None:
        ...

    def canal_e_contato(self) -> tuple[Canal_de_Notificacao | None, Dado_de_Contato | None]:
        ...

    def definir_canal(self, canal: Canal_de_Notificacao, contato: Dado_de_Contato) -> None:
        ...

    def horario_coleta(self) -> HorarioColeta:
        ...

    def definir_horario(self, horario: HorarioColeta) -> None:
        ...


@runtime_checkable
class CofreCredenciais(Protocol):
    """Cofre da Credencial_Unicamp.

    Criptografa/decifra a credencial e garante mascaramento e omissão em logs.
    NUNCA retorna a senha em claro para UI, logs ou notificações (Req 6).
    """

    def armazenar(self, login: str, senha: str) -> None:
        ...

    def obter_para_coleta(self) -> Credencial_Unicamp:
        ...

    def mascarar_para_exibicao(self) -> str:
        ...

    def remover(self) -> None:
        ...


@runtime_checkable
class Agendador(Protocol):
    """Dispara coleta e detecção no horário configurado (Req 1.1, 1.7)."""

    def agendar(self, horario: HorarioColeta, acao: Callable[[], None]) -> None:
        ...

    def executar_ciclo_semanal(self) -> None:
        ...

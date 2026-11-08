"""Implementação de ``ConfigRepo`` sobre SQLite (Tarefa 3.2).

Este módulo implementa o contrato ``notificacoes_ru.nucleo.contratos.ConfigRepo``
sobre o esquema definido em :mod:`notificacoes_ru.persistencia.esquema`
(tabelas ``pratos_monitorados`` e ``configuracao``). Cobre três grupos de
responsabilidades das Configuracoes do Usuario:

* **Pratos monitorados** (Req 2.1–2.5, 2.7): adicionar com *trim* e validação de
  1–100 caracteres, limite de 50 pratos, unicidade por ``nome_normalizado``
  (reuso do Normalizador compartilhado), além de remover e listar.
* **Canal/contato de notificação** (Req 4.3): ler e definir o canal e o
  ``Dado_de_Contato`` associado.
* **Horário de coleta** (Req 1.7): ler e definir o ``HorarioColeta`` configurado.

A validação de regras de negócio vive aqui; a forma do dado (DDL) vive no
módulo de esquema. Nenhuma senha ou credencial é manipulada por este
repositório.
"""

from __future__ import annotations

import sqlite3

from notificacoes_ru.nucleo.modelos import Prato_Monitorado
from notificacoes_ru.nucleo.texto import normalizar
from notificacoes_ru.nucleo.tipos import (
    Canal_de_Notificacao,
    Dado_de_Contato,
    HorarioColeta,
)

# Limites de cadastro de pratos (Req 2.1, 2.2, 2.5).
TAMANHO_MIN_PRATO = 1
TAMANHO_MAX_PRATO = 100
LIMITE_PRATOS = 50

# id fixo da linha única das tabelas ``configuracao`` e ``credencial``.
_ID_CONFIG = 1

# Separador interno usado para serializar o ``HorarioColeta`` no campo TEXT
# ``configuracao.horario_coleta`` (dia_semana|HH:MM). O fuso é persistido na
# coluna dedicada ``configuracao.fuso``.
_SEP_HORARIO = "|"


class ErroValidacaoConfig(ValueError):
    """Erro de validação de uma operação de configuração.

    Usado para sinalizar violações de regra de negócio (nome de prato inválido,
    prato duplicado, limite atingido, contato ausente) preservando o estado
    atual da configuração sem alterá-lo.
    """


class ConfigRepoSQLite:
    """``ConfigRepo`` persistente em SQLite.

    Recebe uma conexão já inicializada (ver
    :func:`notificacoes_ru.persistencia.esquema.inicializar_banco`). Todas as
    operações de escrita são transacionais; em caso de rejeição por validação,
    nenhuma linha é alterada.
    """

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._con = conexao

    # ------------------------------------------------------------------
    # Pratos monitorados (Req 2)
    # ------------------------------------------------------------------
    def pratos_monitorados(self) -> list[Prato_Monitorado]:
        """Lista os pratos monitorados registrados, por ordem de cadastro (Req 2.4)."""
        linhas = self._con.execute(
            "SELECT nome_original, nome_normalizado "
            "FROM pratos_monitorados ORDER BY id ASC;"
        ).fetchall()
        return [
            Prato_Monitorado(
                nome_original=linha["nome_original"],
                nome_normalizado=linha["nome_normalizado"],
            )
            for linha in linhas
        ]

    def adicionar_prato(self, nome: str) -> Prato_Monitorado:
        """Registra um novo ``Prato_Monitorado`` aplicando as regras de cadastro.

        Regras (Req 2.1, 2.2, 2.5, 2.7):

        * remove espaços nas pontas (*trim*);
        * rejeita nome vazio ou com mais de 100 caracteres após o trim;
        * rejeita se o ``nome_normalizado`` já existir na lista (unicidade);
        * rejeita se a lista já tiver 50 pratos (limite).

        Em qualquer rejeição levanta :class:`ErroValidacaoConfig` e a lista atual
        permanece inalterada. Em sucesso retorna o ``Prato_Monitorado`` criado.
        """
        nome_aparado = nome.strip()

        # Req 2.1 / 2.5: tamanho entre 1 e 100 caracteres após o trim.
        if not (TAMANHO_MIN_PRATO <= len(nome_aparado) <= TAMANHO_MAX_PRATO):
            raise ErroValidacaoConfig(
                "O nome do prato é obrigatório e deve ter entre "
                f"{TAMANHO_MIN_PRATO} e {TAMANHO_MAX_PRATO} caracteres."
            )

        nome_normalizado = normalizar(nome_aparado)

        # Após a normalização o texto pode colapsar para vazio (ex.: entrada só
        # de caracteres de espaçamento não capturados pelo strip). Trata como
        # nome inválido para não gravar chave de unicidade vazia.
        if not nome_normalizado:
            raise ErroValidacaoConfig(
                "O nome do prato é obrigatório e deve ter entre "
                f"{TAMANHO_MIN_PRATO} e {TAMANHO_MAX_PRATO} caracteres."
            )

        # Req 2.7: unicidade por nome normalizado.
        ja_existe = self._con.execute(
            "SELECT 1 FROM pratos_monitorados WHERE nome_normalizado = ? LIMIT 1;",
            (nome_normalizado,),
        ).fetchone()
        if ja_existe is not None:
            raise ErroValidacaoConfig("O prato já está cadastrado.")

        # Req 2.2: limite de 50 pratos monitorados.
        total = self._con.execute(
            "SELECT COUNT(*) FROM pratos_monitorados;"
        ).fetchone()[0]
        if total >= LIMITE_PRATOS:
            raise ErroValidacaoConfig(
                f"Limite de {LIMITE_PRATOS} pratos monitorados atingido."
            )

        with self._con:
            self._con.execute(
                "INSERT INTO pratos_monitorados (nome_original, nome_normalizado) "
                "VALUES (?, ?);",
                (nome_aparado, nome_normalizado),
            )

        return Prato_Monitorado(
            nome_original=nome_aparado,
            nome_normalizado=nome_normalizado,
        )

    def remover_prato(self, nome_normalizado: str) -> None:
        """Remove o prato cujo ``nome_normalizado`` corresponda (Req 2.3).

        A chave é normalizada novamente para tolerar entradas com variações de
        caixa/acentuação. Remover um prato ausente é uma operação silenciosa
        (idempotente) — a lista simplesmente não o contém depois.
        """
        chave = normalizar(nome_normalizado)
        with self._con:
            self._con.execute(
                "DELETE FROM pratos_monitorados WHERE nome_normalizado = ?;",
                (chave,),
            )

    # ------------------------------------------------------------------
    # Canal e contato de notificação (Req 4.3)
    # ------------------------------------------------------------------
    def canal_e_contato(
        self,
    ) -> tuple[Canal_de_Notificacao | None, Dado_de_Contato | None]:
        """Retorna o canal e o contato configurados, ou ``(None, None)``.

        A validação de formato do contato por canal (Req 4.8) é
        responsabilidade da camada que implementa ``CanalNotificacao``; aqui
        apenas persistimos e recuperamos o par escolhido pelo Usuario.
        """
        linha = self._con.execute(
            "SELECT canal, contato FROM configuracao WHERE id = ?;",
            (_ID_CONFIG,),
        ).fetchone()
        if linha is None or linha["canal"] is None:
            return (None, None)

        canal = Canal_de_Notificacao(linha["canal"])
        contato_valor = linha["contato"]
        contato = (
            Dado_de_Contato(canal=canal, valor=contato_valor)
            if contato_valor is not None
            else None
        )
        return (canal, contato)

    def definir_canal(
        self,
        canal: Canal_de_Notificacao,
        contato: Dado_de_Contato,
    ) -> None:
        """Define o canal e o contato de notificação (Req 4.3).

        Rejeita contato ausente/vazio (Req 4.8) e exige que o canal do
        ``Dado_de_Contato`` coincida com o canal informado, evitando
        configurações inconsistentes. A linha de configuração é criada caso
        ainda não exista (upsert), preservando o fuso/horário já gravados.
        """
        if contato is None or not contato.valor.strip():
            raise ErroValidacaoConfig(
                "O dado de contato é obrigatório para o canal selecionado."
            )
        if contato.canal != canal:
            raise ErroValidacaoConfig(
                "O canal do contato não corresponde ao canal informado."
            )

        with self._con:
            self._con.execute(
                "INSERT INTO configuracao (id, canal, contato) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET canal = excluded.canal, "
                "contato = excluded.contato;",
                (_ID_CONFIG, canal.value, contato.valor),
            )

    # ------------------------------------------------------------------
    # Horário de coleta (Req 1.7)
    # ------------------------------------------------------------------
    def horario_coleta(self) -> HorarioColeta:
        """Retorna o ``HorarioColeta`` configurado ou o padrão do design.

        O padrão (sábado 11:00, fuso ``America/Sao_Paulo``) vem dos valores
        default de :class:`HorarioColeta` (Req 1.7) e é retornado quando não há
        horário persistido.
        """
        linha = self._con.execute(
            "SELECT horario_coleta, fuso FROM configuracao WHERE id = ?;",
            (_ID_CONFIG,),
        ).fetchone()
        if linha is None or linha["horario_coleta"] is None:
            return HorarioColeta(hora=11, minuto=0)

        return self._desserializar_horario(linha["horario_coleta"], linha["fuso"])

    def definir_horario(self, horario: HorarioColeta) -> None:
        """Persiste o ``HorarioColeta`` configurado pelo Usuario (Req 1.7).

        Serializa dia da semana + hora/minuto no campo TEXT ``horario_coleta`` e
        grava o fuso na coluna dedicada, preservando canal/contato já
        existentes (upsert).
        """
        texto_horario = self._serializar_horario(horario)
        with self._con:
            self._con.execute(
                "INSERT INTO configuracao (id, horario_coleta, fuso) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "horario_coleta = excluded.horario_coleta, fuso = excluded.fuso;",
                (_ID_CONFIG, texto_horario, horario.fuso),
            )

    # ------------------------------------------------------------------
    # Serialização interna do HorarioColeta
    # ------------------------------------------------------------------
    @staticmethod
    def _serializar_horario(horario: HorarioColeta) -> str:
        """Serializa ``HorarioColeta`` como ``"dia_semana|HH:MM"``."""
        return f"{horario.dia_semana}{_SEP_HORARIO}{horario.hora:02d}:{horario.minuto:02d}"

    @staticmethod
    def _desserializar_horario(texto: str, fuso: str | None) -> HorarioColeta:
        """Reconstrói ``HorarioColeta`` a partir do texto persistido."""
        dia_semana, _, relogio = texto.partition(_SEP_HORARIO)
        hora_str, _, minuto_str = relogio.partition(":")
        return HorarioColeta(
            hora=int(hora_str),
            minuto=int(minuto_str),
            fuso=fuso or "America/Sao_Paulo",
            dia_semana=dia_semana,
        )

"""Cofre de Credenciais com Fernet (Tarefa 5.1).

Implementa o contrato ``nucleo.CofreCredenciais`` usando criptografia
autenticada de campo via :class:`cryptography.fernet.Fernet` (AES-128-CBC +
HMAC-SHA256), conforme a stack sugerida no design.

Garantias (Requirement 6):

* **6.2** — a senha é criptografada em repouso; o valor persistido
  (``senha_criptografada`` BLOB na tabela ``credencial``) nunca é o texto claro.
* **6.3** — login ou senha vazios (ou só espaços) são rejeitados e qualquer
  credencial previamente armazenada permanece inalterada.
* **6.4** — a exibição da senha é sempre mascarada.
* **6.5** — a senha em claro é omitida de ``repr``/logs; o cofre só revela o
  texto claro via :meth:`obter_para_coleta`, de uso interno da coleta.
* **6.8** — a remoção apaga a credencial armazenada.

## Gestão de chave

O Fernet exige uma chave simétrica (32 bytes url-safe base64). A chave é um
segredo separado do banco de dados: quem tem apenas o arquivo ``.db`` (com a
senha cifrada) não consegue decifrá-la sem a chave. Para operação persistente
use :func:`carregar_ou_criar_chave`, que lê a chave de um arquivo com permissão
restrita (ou a gera na primeira execução). Em testes, uma chave em memória de
:func:`gerar_chave` é suficiente.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path
from typing import Union

from cryptography.fernet import Fernet

from notificacoes_ru.nucleo.modelos import Credencial_Unicamp

# Caractere usado para mascarar a senha na exibição (Req 6.4).
CARACTERE_MASCARA = "*"

# Linha única da credencial (ver esquema: ``credencial.id`` fixo em 1).
_ID_CREDENCIAL = 1


class CredencialAusenteError(RuntimeError):
    """Levantada ao pedir a credencial para coleta quando nenhuma existe."""


def gerar_chave() -> bytes:
    """Gera uma nova chave Fernet (32 bytes codificados em base64 url-safe)."""
    return Fernet.generate_key()


def carregar_ou_criar_chave(caminho: Union[str, Path]) -> bytes:
    """Carrega a chave Fernet de ``caminho`` ou a cria na primeira execução.

    Ao criar, o arquivo recebe permissão restrita (0o600 em plataformas POSIX)
    para reduzir o risco de leitura por outros usuários. A chave é um segredo
    e não deve ser versionada nem registrada em log.
    """
    alvo = Path(caminho)
    if alvo.exists():
        return alvo.read_bytes().strip()

    chave = gerar_chave()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    # Cria com permissão restrita desde o início quando o SO suportar.
    fd = os.open(str(alvo), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, chave)
    finally:
        os.close(fd)
    try:  # Em POSIX reforça 0o600; em Windows é no-op tolerado.
        os.chmod(alvo, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return chave


class CofreCredenciaisFernet:
    """Implementação de ``nucleo.CofreCredenciais`` com Fernet + SQLite.

    A senha é cifrada antes de tocar o banco e só é decifrada dentro de
    :meth:`obter_para_coleta`. Nenhuma representação da instância expõe a senha
    (em claro ou cifrada) — ver :meth:`__repr__` (Req 6.5).
    """

    def __init__(self, conexao: sqlite3.Connection, chave: bytes) -> None:
        """Cria o cofre sobre uma conexão SQLite já inicializada.

        ``chave`` é uma chave Fernet válida (ver :func:`gerar_chave` ou
        :func:`carregar_ou_criar_chave`). A conexão deve conter a tabela
        ``credencial`` (ver ``persistencia.esquema``).
        """
        self._con = conexao
        # ``Fernet`` valida o formato da chave aqui; mantido privado e sem repr.
        self._fernet = Fernet(chave)

    # -- Escrita -----------------------------------------------------------

    def armazenar(self, login: str, senha: str) -> None:
        """Armazena a credencial com a senha cifrada em repouso (Req 6.2).

        Rejeita login ou senha vazios — inclusive compostos apenas de espaços —
        levantando :class:`ValueError` e preservando qualquer credencial já
        armazenada (Req 6.3). A mensagem de erro não inclui o valor da senha.
        """
        if not login or not login.strip() or not senha or not senha.strip():
            raise ValueError("login e senha são obrigatórios")

        senha_cifrada = self._fernet.encrypt(senha.encode("utf-8"))
        # UPSERT na linha única: insere na primeira vez, atualiza nas seguintes.
        with self._con:
            self._con.execute(
                """
                INSERT INTO credencial (id, login, senha_criptografada)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    login = excluded.login,
                    senha_criptografada = excluded.senha_criptografada;
                """,
                (_ID_CREDENCIAL, login, senha_cifrada),
            )

    def remover(self) -> None:
        """Remove a credencial armazenada, se houver (Req 6.8). Idempotente."""
        with self._con:
            self._con.execute(
                "DELETE FROM credencial WHERE id = ?;", (_ID_CREDENCIAL,)
            )

    # -- Leitura -----------------------------------------------------------

    def existe(self) -> bool:
        """Indica se há uma credencial armazenada."""
        return self._buscar_linha() is not None

    def obter_para_coleta(self) -> Credencial_Unicamp:
        """Retorna a credencial para uso **interno** da coleta (Req 6.1).

        O modelo ``Credencial_Unicamp`` carrega a senha ainda cifrada em
        ``senha_criptografada``; o texto claro é obtido sob demanda via
        :meth:`obter_senha_em_claro`, nunca persistido nem exposto em ``repr``.

        Levanta :class:`CredencialAusenteError` quando nenhuma credencial foi
        armazenada.
        """
        linha = self._buscar_linha()
        if linha is None:
            raise CredencialAusenteError("nenhuma credencial armazenada")
        return Credencial_Unicamp(
            login=linha["login"],
            senha_criptografada=bytes(linha["senha_criptografada"]),
        )

    def obter_senha_em_claro(self) -> str:
        """Decifra e retorna a senha em claro (uso interno da coleta).

        Separada de :meth:`obter_para_coleta` para deixar explícito e auditável
        o único ponto em que o texto claro é materializado. O chamador é
        responsável por não registrar o valor em log nem exibi-lo (Req 6.5).
        """
        linha = self._buscar_linha()
        if linha is None:
            raise CredencialAusenteError("nenhuma credencial armazenada")
        return self._fernet.decrypt(
            bytes(linha["senha_criptografada"])
        ).decode("utf-8")

    def mascarar_para_exibicao(self) -> str:
        """Retorna a senha mascarada para exibição na UI (Req 6.4).

        Substitui todos os caracteres da senha por :data:`CARACTERE_MASCARA`,
        preservando o comprimento original (decifrado apenas para contar os
        caracteres, sem expor o valor). Retorna string vazia se não há
        credencial.
        """
        linha = self._buscar_linha()
        if linha is None:
            return ""
        senha = self._fernet.decrypt(bytes(linha["senha_criptografada"])).decode(
            "utf-8"
        )
        return CARACTERE_MASCARA * len(senha)

    # -- Internos ----------------------------------------------------------

    def _buscar_linha(self) -> sqlite3.Row | None:
        return self._con.execute(
            "SELECT login, senha_criptografada FROM credencial WHERE id = ?;",
            (_ID_CREDENCIAL,),
        ).fetchone()

    def __repr__(self) -> str:
        """Representação segura: nunca inclui a senha nem a chave (Req 6.5)."""
        estado = "com credencial" if self.existe() else "vazio"
        return f"<CofreCredenciaisFernet {estado}>"

"""Normalizador de Texto compartilhado.

Centraliza a regra "insensível a maiúsculas/minúsculas e acentuação" usada pelo
cadastro de pratos (Req 2), pela detecção (Req 3) e pela busca no histórico
(Req 5). Como descrito na seção *Components and Interfaces* do design, expõe
duas funções puras: ``normalizar`` e ``contem``.

São funções sem estado e sem efeitos colaterais, dependendo apenas da
biblioteca padrão (``unicodedata``) — ver stack sugerida no design.
"""

from __future__ import annotations

import unicodedata


def normalizar(texto: str) -> str:
    """Normaliza ``texto`` para comparação insensível a caixa e acentuação.

    Passos (nesta ordem):

    1. Aplica a forma de compatibilidade Unicode NFKD, decompondo caracteres
       acentuados em caractere base + marcas combinantes.
    2. Remove as marcas de acento (diacríticos, categoria Unicode ``Mn``).
    3. Converte para minúsculas.
    4. Colapsa sequências de espaços em branco internas em um único espaço e
       remove espaços nas pontas.

    A função é idempotente: ``normalizar(normalizar(t)) == normalizar(t)``
    (Property 1).
    """
    # 1. Decomposição de compatibilidade (NFKD).
    decomposto = unicodedata.normalize("NFKD", texto)

    # 2. Remoção de diacríticos (marcas não espaçadas, categoria "Mn").
    sem_acentos = "".join(
        caractere
        for caractere in decomposto
        if not unicodedata.combining(caractere)
    )

    # 3. Minúsculas.
    minusculo = sem_acentos.casefold()

    # 4. Colapso de espaços internos + trim das pontas.
    #    ``str.split()`` sem argumentos divide por qualquer sequência de
    #    whitespace e descarta as pontas vazias; ``join`` recompõe com um único
    #    espaço entre os tokens.
    return " ".join(minusculo.split())


def contem(item_cardapio: str, nome_prato: str) -> bool:
    """Indica se ``nome_prato`` ocorre dentro de ``item_cardapio``.

    Retorna ``True`` se e somente se ``normalizar(nome_prato)`` é uma
    subsequência contígua (substring) de ``normalizar(item_cardapio)``,
    comparando ambos de forma insensível a maiúsculas/minúsculas e a acentuação
    (Property 2; Req 2.6, 3.1).
    """
    return normalizar(nome_prato) in normalizar(item_cardapio)

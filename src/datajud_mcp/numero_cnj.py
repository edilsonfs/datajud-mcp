"""Leitura e validação do número único de processo (Resolução CNJ 65/2008).

O número tem 20 dígitos no formato ``NNNNNNN-DD.AAAA.J.TR.OOOO``:

===========  ====================================================
NNNNNNN (7)  sequencial por ano e por unidade de origem
DD (2)       dígito verificador, módulo 97 base 10 (ISO 7064)
AAAA (4)     ano do ajuizamento
J (1)        segmento do Poder Judiciário
TR (2)       tribunal dentro do segmento
OOOO (4)     unidade de origem (vara, comarca, zona eleitoral)
===========  ====================================================

Ler esses campos permite responder "em qual tribunal esse processo
corre?" sem que o usuário precise saber a sigla — que é o principal
atrito de quem não é servidor do Judiciário.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .tribunais import SEGMENTOS, por_segmento

_SO_DIGITOS = re.compile(r"\D")


class NumeroCNJ(NamedTuple):
    """Um número CNJ já decomposto e verificado."""

    numero: str            # 20 dígitos, sem máscara
    formatado: str         # com a máscara oficial
    sequencial: str
    digito_verificador: str
    ano: int
    segmento: int
    codigo_tr: int
    origem: str
    valido: bool           # o dígito verificador confere?
    justica: str
    tribunais: list[str]   # siglas prováveis para consulta no DataJud


def limpar(numero: str) -> str:
    """Remove máscara e espaços, devolvendo apenas os dígitos."""
    return _SO_DIGITOS.sub("", numero or "")


def formatar(numero: str) -> str:
    """Aplica a máscara oficial a um número de 20 dígitos.

    Números com tamanho diferente são devolvidos como estão.
    """
    n = limpar(numero)
    if len(n) != 20:
        return numero
    return f"{n[0:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:20]}"


def calcular_digito(numero: str) -> str | None:
    """Calcula o dígito verificador (módulo 97 base 10).

    Aceita o número completo de 20 dígitos (o DV informado é ignorado no
    cálculo) ou os 18 dígitos sem o DV. Devolve ``None`` se o tamanho
    não permitir o cálculo.
    """
    n = limpar(numero)
    if len(n) == 20:
        sem_dv = n[0:7] + n[9:20]
    elif len(n) == 18:
        sem_dv = n
    else:
        return None
    resto = int(sem_dv + "00") % 97
    return f"{98 - resto:02d}"


def analisar(numero: str) -> NumeroCNJ | None:
    """Decompõe e valida um número CNJ.

    Devolve ``None`` quando o texto não tem 20 dígitos — nesse caso não
    há o que interpretar. Um número com 20 dígitos e dígito verificador
    incorreto ainda é devolvido, com ``valido=False``, porque o resto da
    informação continua útil para orientar o usuário.
    """
    n = limpar(numero)
    if len(n) != 20:
        return None

    segmento = int(n[13])
    codigo_tr = int(n[14:16])
    esperado = calcular_digito(n)

    return NumeroCNJ(
        numero=n,
        formatado=formatar(n),
        sequencial=n[0:7],
        digito_verificador=n[7:9],
        ano=int(n[9:13]),
        segmento=segmento,
        codigo_tr=codigo_tr,
        origem=n[16:20],
        valido=(esperado == n[7:9]),
        justica=SEGMENTOS.get(segmento, "Segmento desconhecido"),
        tribunais=por_segmento(segmento, codigo_tr),
    )


def extrair(texto: str) -> list[str]:
    """Extrai números CNJ de um texto livre.

    Reconhece tanto a forma com máscara quanto 20 dígitos seguidos, que
    é como advogados costumam colar números vindos de petições e
    sistemas processuais.
    """
    achados: list[str] = []
    padrao = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}|\d{20}")
    for m in padrao.finditer(texto or ""):
        n = limpar(m.group())
        if len(n) == 20 and n not in achados:
            achados.append(n)
    return achados

"""Montagem das consultas Elasticsearch enviadas ao DataJud.

Concentrar aqui a construção das queries evita o problema do servidor
legado, em que cada ferramenta repetia o mesmo bloco de filtros e as
correções precisavam ser aplicadas cinco vezes.
"""

from __future__ import annotations

import re
from typing import Any

# Agrupamentos aceitos por ``montar_agregacao``: nome amigável -> campo.
CAMPOS_AGRUPAVEIS: dict[str, str] = {
    "classe": "classe.codigo",
    "assunto": "assuntos.codigo",
    "orgao": "orgaoJulgador.codigo",
    "grau": "grau",
    "formato": "formato.codigo",
    "sistema": "sistema.codigo",
    "ano": "dataAjuizamento",
}

_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FiltroInvalido(ValueError):
    """Filtro informado pelo usuário que não pode ser traduzido em query."""


def _validar_data(rotulo: str, valor: str | None) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    if not _DATA_ISO.match(valor):
        raise FiltroInvalido(
            f"{rotulo} deve estar no formato AAAA-MM-DD (ex: 2024-01-31). "
            f"Recebido: '{valor}'."
        )
    return valor


def montar_filtros(
    codigo_classe: int | None = None,
    nome_classe: str | None = None,
    codigo_assunto: int | None = None,
    nome_assunto: str | None = None,
    codigo_orgao: int | None = None,
    nome_orgao: str | None = None,
    codigo_municipio_ibge: int | None = None,
    grau: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
) -> list[dict[str, Any]]:
    """Traduz filtros em linguagem de negócio para cláusulas ``must``.

    Códigos usam ``term`` (correspondência exata); nomes usam
    ``match_phrase``, que tolera diferença de caixa e acentuação mas
    exige as palavras na ordem informada — o comportamento que menos
    surpreende quem digita "Execução Fiscal" ou "1ª Vara Cível".
    """
    must: list[dict[str, Any]] = []

    if codigo_classe is not None:
        must.append({"term": {"classe.codigo": codigo_classe}})
    if nome_classe:
        must.append({"match_phrase": {"classe.nome": nome_classe}})
    if codigo_assunto is not None:
        must.append({"term": {"assuntos.codigo": codigo_assunto}})
    if nome_assunto:
        must.append({"match_phrase": {"assuntos.nome": nome_assunto}})
    if codigo_orgao is not None:
        must.append({"term": {"orgaoJulgador.codigo": codigo_orgao}})
    if nome_orgao:
        must.append({"match_phrase": {"orgaoJulgador.nome": nome_orgao}})
    if codigo_municipio_ibge is not None:
        must.append(
            {"term": {"orgaoJulgador.codigoMunicipioIBGE": codigo_municipio_ibge}}
        )
    if grau:
        must.append({"term": {"grau": grau.upper().strip()}})

    inicio = _validar_data("data_inicio", data_inicio)
    fim = _validar_data("data_fim", data_fim)
    if inicio or fim:
        intervalo: dict[str, str] = {}
        if inicio:
            intervalo["gte"] = inicio
        if fim:
            intervalo["lte"] = fim
        must.append({"range": {"dataAjuizamento": intervalo}})

    return must


def montar_query(must: list[dict[str, Any]]) -> dict[str, Any]:
    """Envolve as cláusulas em uma query, ou devolve ``match_all``."""
    return {"bool": {"must": must}} if must else {"match_all": {}}


def montar_busca(
    must: list[dict[str, Any]],
    tamanho: int = 20,
    search_after: list[Any] | None = None,
    ordenar_por_ajuizamento: bool = False,
) -> dict[str, Any]:
    """Monta o corpo de uma busca paginável.

    A ordenação padrão é por ``@timestamp`` porque é o único campo
    presente em todos os documentos de todos os tribunais; sem uma
    ordenação estável o ``search_after`` não funciona.
    """
    campo_ordem = "dataAjuizamento" if ordenar_por_ajuizamento else "@timestamp"
    corpo: dict[str, Any] = {
        "size": max(1, min(1000, tamanho)),
        "track_total_hits": True,
        "query": montar_query(must),
        "sort": [{campo_ordem: {"order": "asc"}}],
    }
    if search_after:
        corpo["search_after"] = search_after
    return corpo


def montar_contagem(must: list[dict[str, Any]]) -> dict[str, Any]:
    """Monta uma consulta que só conta, sem trazer documentos."""
    return {"size": 0, "track_total_hits": True, "query": montar_query(must)}


def montar_agregacao(
    agrupar_por: str,
    must: list[dict[str, Any]],
    tamanho: int = 30,
) -> dict[str, Any]:
    """Monta uma agregação por campo categórico.

    Para todo agrupamento por código, embute um ``top_hits`` de um único
    documento. É ele que permite recuperar o rótulo **correto** de cada
    código: ``assuntos`` é um vetor, e uma sub-agregação por nome
    misturaria os nomes dos demais assuntos do mesmo processo.
    """
    if agrupar_por not in CAMPOS_AGRUPAVEIS:
        raise FiltroInvalido(
            f"Agrupamento '{agrupar_por}' inválido. Use um de: "
            + ", ".join(CAMPOS_AGRUPAVEIS)
        )

    if agrupar_por == "ano":
        agregacao: dict[str, Any] = {
            "grupos": {
                "date_histogram": {
                    "field": "dataAjuizamento",
                    "calendar_interval": "year",
                    "format": "yyyy",
                    "min_doc_count": 1,
                }
            }
        }
    else:
        campo = CAMPOS_AGRUPAVEIS[agrupar_por]
        agregacao = {
            "grupos": {
                "terms": {"field": campo, "size": max(1, min(200, tamanho))},
            }
        }
        if agrupar_por != "grau":
            agregacao["grupos"]["aggs"] = {
                "exemplo": {
                    "top_hits": {
                        "size": 1,
                        "_source": [
                            "classe", "assuntos", "orgaoJulgador",
                            "formato", "sistema",
                        ],
                    }
                }
            }

    return {
        "size": 0,
        "track_total_hits": True,
        "query": montar_query(must),
        "aggs": agregacao,
    }


def montar_por_numero(numero: str, tamanho: int = 5) -> dict[str, Any]:
    """Monta a busca pelo número do processo, já sem máscara."""
    return {
        "size": tamanho,
        "track_total_hits": True,
        "query": {"match": {"numeroProcesso": numero}},
    }


def montar_amostra_para_codigos(
    campo: str,
    termo: str,
    tamanho: int = 100,
) -> dict[str, Any]:
    """Monta a busca usada para descobrir códigos da TPU a partir de um termo.

    Em vez de agregar por nome — que sofre do mesmo embaralhamento de
    vetores — traz uma amostra de processos e deixa o chamador extrair os
    pares código/nome diretamente dos documentos, onde eles já vêm
    corretamente pareados.
    """
    return {
        "size": max(1, min(200, tamanho)),
        "track_total_hits": True,
        "query": {"match": {campo: termo}},
        "_source": ["classe", "assuntos"],
    }

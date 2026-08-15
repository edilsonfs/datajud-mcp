"""Montagem das consultas Elasticsearch enviadas ao DataJud.

Concentrar aqui a construção das queries evita o problema do servidor
legado, em que cada ferramenta repetia o mesmo bloco de filtros e as
correções precisavam ser aplicadas cinco vezes.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Primeiro ano da série histórica oferecida pelas agregações por ano.
ANO_INICIAL_PADRAO = 2000


def _anos_da_serie(quantidade: int) -> list[int]:
    """Anos cobertos por uma agregação por ano, do mais antigo ao atual."""
    ano_final = date.today().year
    quantidade = max(1, min(60, quantidade))
    ano_inicial = max(ANO_INICIAL_PADRAO, ano_final - quantidade + 1)
    return list(range(ano_inicial, ano_final + 1))

# Agrupamentos aceitos por ``montar_agregacao``: nome amigável -> campo.
CAMPOS_AGRUPAVEIS: dict[str, str] = {
    "classe": "classe.codigo",
    "assunto": "assuntos.codigo",
    "orgao": "orgaoJulgador.codigo",
    # grau é indexado como texto analisado; só o subcampo keyword aceita
    # agregação.
    "grau": "grau.keyword",
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
        # match, e não term: grau é campo de texto analisado, então o
        # termo exato "G1" não casaria com o índice em minúsculas.
        must.append({"match": {"grau": grau.upper().strip()}})

    inicio = _validar_data("data_inicio", data_inicio)
    fim = _validar_data("data_fim", data_fim)
    if inicio or fim:
        must.append(intervalo_de_ajuizamento(inicio, fim))

    return must


def intervalo_de_ajuizamento(
    inicio: str | None,
    fim: str | None,
) -> dict[str, Any]:
    """Filtra por data de ajuizamento cobrindo as duas formas da base.

    ``dataAjuizamento`` é um campo de data, mas boa parte dos tribunais
    grava nele o número ``yyyyMMddHHmmss`` (ex.: ``20191113191041``).
    O Elasticsearch lê esse número como epoch em milissegundos, e o
    processo de 2019 vai parar no ano 2610. Um filtro escrito só na
    forma ISO perde silenciosamente todos esses registros — em alguns
    tribunais, o acervo inteiro.

    A saída casa qualquer uma das duas representações.
    """
    iso: dict[str, str] = {}
    numerico: dict[str, int] = {}

    if inicio:
        iso["gte"] = inicio
        numerico["gte"] = int(inicio.replace("-", "") + "000000")
    if fim:
        iso["lte"] = fim
        numerico["lte"] = int(fim.replace("-", "") + "235959")

    return {
        "bool": {
            "should": [
                {"range": {"dataAjuizamento": iso}},
                {"range": {"dataAjuizamento": numerico}},
            ],
            "minimum_should_match": 1,
        }
    }


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
        # Um date_histogram devolveria "2610" para processos de 2019 —
        # ver intervalo_de_ajuizamento. Um bucket explícito por ano, com
        # as duas representações, é o que dá uma série confiável.
        agregacao: dict[str, Any] = {
            "grupos": {
                "filters": {
                    "filters": {
                        str(ano): intervalo_de_ajuizamento(
                            f"{ano}-01-01", f"{ano}-12-31"
                        )
                        for ano in _anos_da_serie(tamanho)
                    }
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

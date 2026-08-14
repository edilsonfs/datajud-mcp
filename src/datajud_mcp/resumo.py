"""Conversão das respostas da API em objetos enxutos para o modelo.

Um único processo do DataJud pode trazer centenas de movimentos. Passar
isso cru para um LLM estoura a janela de contexto e piora a resposta, em
vez de melhorá-la. Aqui cada resposta é reduzida ao que o usuário
realmente lê, com o detalhe completo disponível sob demanda.
"""

from __future__ import annotations

from typing import Any

from .numero_cnj import formatar


def _campo(fonte: dict[str, Any], chave: str) -> dict[str, Any]:
    valor = fonte.get(chave)
    return valor if isinstance(valor, dict) else {}


def resumir_processo(fonte: dict[str, Any]) -> dict[str, Any]:
    """Resume um processo, preservando o que orienta a próxima pergunta."""
    classe = _campo(fonte, "classe")
    orgao = _campo(fonte, "orgaoJulgador")
    movimentos = fonte.get("movimentos") or []

    ultimo: dict[str, Any] = {}
    if movimentos:
        # A API não garante ordem cronológica dos movimentos.
        ultimo = max(
            (m for m in movimentos if isinstance(m, dict)),
            key=lambda m: str(m.get("dataHora") or ""),
            default={},
        )

    return {
        "numeroProcesso": formatar(fonte.get("numeroProcesso") or ""),
        "tribunal": fonte.get("tribunal"),
        "grau": fonte.get("grau"),
        "dataAjuizamento": fonte.get("dataAjuizamento"),
        "classe": {
            "codigo": classe.get("codigo"),
            "nome": classe.get("nome"),
        },
        "orgaoJulgador": {
            "codigo": orgao.get("codigo"),
            "nome": orgao.get("nome"),
            "codigoMunicipioIBGE": orgao.get("codigoMunicipioIBGE"),
        },
        "assuntos": [
            {"codigo": a.get("codigo"), "nome": a.get("nome")}
            for a in (fonte.get("assuntos") or [])
            if isinstance(a, dict)
        ],
        "sistema": _campo(fonte, "sistema").get("nome"),
        "formato": _campo(fonte, "formato").get("nome"),
        "nivelSigilo": fonte.get("nivelSigilo"),
        "qtdMovimentos": len(movimentos),
        "ultimoMovimento": {
            "nome": ultimo.get("nome"),
            "dataHora": ultimo.get("dataHora"),
        } if ultimo else None,
        "atualizadoEm": fonte.get("@timestamp"),
    }


def resumir_movimentos(
    fonte: dict[str, Any],
    limite: int = 30,
    ordem_decrescente: bool = True,
) -> dict[str, Any]:
    """Devolve a linha do tempo do processo, do mais recente ao mais antigo.

    Args:
        fonte: documento ``_source`` do processo.
        limite: quantos movimentos retornar (1-500).
        ordem_decrescente: ``True`` começa pelo movimento mais recente.
    """
    brutos = [m for m in (fonte.get("movimentos") or []) if isinstance(m, dict)]
    ordenados = sorted(
        brutos,
        key=lambda m: str(m.get("dataHora") or ""),
        reverse=ordem_decrescente,
    )
    limite = max(1, min(500, limite))

    linha_do_tempo = []
    for m in ordenados[:limite]:
        item: dict[str, Any] = {
            "dataHora": m.get("dataHora"),
            "codigo": m.get("codigo"),
            "nome": m.get("nome"),
        }
        complementos = [
            c.get("descricao") or c.get("nome")
            for c in (m.get("complementosTabelados") or [])
            if isinstance(c, dict)
        ]
        complementos = [c for c in complementos if c]
        if complementos:
            item["complementos"] = complementos
        linha_do_tempo.append(item)

    return {
        "numeroProcesso": formatar(fonte.get("numeroProcesso") or ""),
        "totalMovimentos": len(brutos),
        "exibindo": len(linha_do_tempo),
        "movimentos": linha_do_tempo,
    }


def resumir_resposta(
    resposta: dict[str, Any],
    detalhe_completo: bool = False,
) -> dict[str, Any]:
    """Resume uma resposta de busca, incluindo o cursor de paginação."""
    hits_bloco = resposta.get("hits", {}) or {}
    total = hits_bloco.get("total", {})
    if isinstance(total, dict):
        total_valor = total.get("value", 0)
        relacao = total.get("relation", "eq")
    else:
        total_valor, relacao = total, "eq"

    hits = hits_bloco.get("hits", []) or []
    if detalhe_completo:
        processos = [h.get("_source", {}) for h in hits]
    else:
        processos = [resumir_processo(h.get("_source", {}) or {}) for h in hits]

    saida: dict[str, Any] = {
        "total": total_valor,
        "totalExato": relacao == "eq",
        "retornados": len(hits),
        "processos": processos,
    }
    if hits and hits[-1].get("sort"):
        saida["proximaPagina"] = hits[-1]["sort"]
        saida["comoPaginar"] = (
            "Repita a mesma busca informando search_after com o valor de "
            "proximaPagina para obter os próximos resultados."
        )
    return saida


def extrair_buckets(
    resposta: dict[str, Any],
    agrupar_por: str,
) -> list[dict[str, Any]]:
    """Converte a agregação em uma lista de grupos já rotulados.

    O rótulo sai do documento de exemplo embutido pela agregação, e não
    de uma sub-agregação por nome: em campos vetoriais como ``assuntos``,
    a sub-agregação devolveria o nome de outro assunto do mesmo processo.
    """
    grupos = (resposta.get("aggregations", {}) or {}).get("grupos", {}) or {}
    buckets = grupos.get("buckets", []) or []

    resultado: list[dict[str, Any]] = []
    for b in buckets:
        chave = b.get("key_as_string", b.get("key"))
        item: dict[str, Any] = {
            "valor": chave,
            "quantidade": b.get("doc_count", 0),
        }

        exemplo_hits = (
            (b.get("exemplo", {}) or {}).get("hits", {}) or {}
        ).get("hits", []) or []
        if exemplo_hits:
            nome = _rotular(
                exemplo_hits[0].get("_source", {}) or {},
                agrupar_por,
                b.get("key"),
            )
            if nome:
                item["nome"] = nome

        resultado.append(item)
    return resultado


def _rotular(fonte: dict[str, Any], agrupar_por: str, codigo: Any) -> str | None:
    if agrupar_por == "assunto":
        for a in fonte.get("assuntos") or []:
            if isinstance(a, dict) and a.get("codigo") == codigo:
                return a.get("nome")
        return None

    chaves = {
        "classe": "classe",
        "orgao": "orgaoJulgador",
        "formato": "formato",
        "sistema": "sistema",
    }
    bloco = _campo(fonte, chaves.get(agrupar_por, ""))
    return bloco.get("nome") or None

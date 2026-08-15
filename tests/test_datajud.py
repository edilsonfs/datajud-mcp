"""Testes do pacote datajud-mcp.

Os testes marcados com ``rede`` consultam a API real do CNJ e são os
únicos capazes de detectar mudança de alias ou de contrato da API — que
é justamente o tipo de quebra que passou despercebida na versão
anterior deste servidor. Rode-os com ``pytest -m rede``.
"""

from __future__ import annotations

import pytest

from datajud_mcp import filtros, numero_cnj, resumo, tribunais

# ---------------------------------------------------------------- número CNJ


def test_digito_verificador_de_numero_real():
    # Processo real do TRF5, colhido da própria API.
    assert numero_cnj.calcular_digito("00018980720234058103") == "07"


def test_digito_verificador_rejeita_numero_adulterado():
    # Mesmo processo com o sequencial trocado de 0001898 para 0001899:
    # o dígito calculado precisa mudar.
    assert numero_cnj.calcular_digito("00018990720234058103") != "07"


def test_analise_identifica_tribunal_estadual():
    a = numero_cnj.analisar("0000001-02.2024.8.17.0001")
    assert a is not None
    assert a.ano == 2024
    assert a.segmento == 8
    assert a.codigo_tr == 17
    assert a.tribunais == ["TJPE"]
    assert a.justica == "Justiça Estadual"


def test_analise_marca_digito_verificador_incorreto():
    a = numero_cnj.analisar("00000010020248170001")
    assert a is not None
    assert a.valido is False


def test_analise_recusa_numero_incompleto():
    assert numero_cnj.analisar("123456") is None


def test_formatacao_aplica_mascara_oficial():
    assert numero_cnj.formatar("00018980720234058103") == (
        "0001898-07.2023.4.05.8103"
    )


def test_extracao_de_numeros_em_texto_livre():
    texto = (
        "Trata-se do processo 0001898-07.2023.4.05.8103, apensado ao "
        "00000010220248170001."
    )
    assert numero_cnj.extrair(texto) == [
        "00018980720234058103",
        "00000010220248170001",
    ]


def test_trf6_convive_com_trf1_no_mesmo_codigo():
    # O TRF6 foi desmembrado do TRF1 e herdou o acervo de Minas Gerais,
    # então o par 4.01 precisa devolver os dois.
    assert set(tribunais.por_segmento(4, 1)) == {"TRF1", "TRF6"}


# ----------------------------------------------------------------- tribunais


def test_catalogo_tem_os_91_tribunais():
    assert len(tribunais.TRIBUNAIS) == 91


def test_alias_eleitoral_usa_hifen():
    # Regressão: a versão anterior gerava "api_publica_trepe" e os 27
    # TREs devolviam 404.
    assert tribunais.alias_de("TREPE") == "api_publica_tre-pe"
    assert tribunais.alias_de("TREDF") == "api_publica_tre-df"


def test_alias_dos_demais_segmentos_nao_usa_hifen():
    assert tribunais.alias_de("TJPE") == "api_publica_tjpe"
    assert tribunais.alias_de("TRT6") == "api_publica_trt6"
    assert tribunais.alias_de("TJDFT") == "api_publica_tjdft"


def test_normalizacao_aceita_grafias_do_usuario():
    assert tribunais.alias_de("tjsp") == "api_publica_tjsp"
    assert tribunais.alias_de("TRE-PE") == "api_publica_tre-pe"
    assert tribunais.alias_de("TJDF") == "api_publica_tjdft"


def test_sigla_inexistente_devolve_none():
    assert tribunais.obter("TJXX") is None


def test_busca_por_estado_alcanca_todos_os_ramos():
    # Quem procura "Pernambuco" deve achar também o TRF e o TRT que
    # atendem o estado, não só os tribunais com PE na sigla.
    assert {t.sigla for t in tribunais.buscar("Pernambuco")} == {
        "TJPE", "TREPE", "TRF5", "TRT6"
    }


def test_busca_por_ramo_de_justica():
    assert len(tribunais.buscar("Justiça Militar Estadual")) == 3


# ------------------------------------------------------------------- filtros


def test_codigos_usam_term_e_nomes_usam_match_phrase():
    must = filtros.montar_filtros(codigo_classe=1116, nome_assunto="Dano Moral")
    assert {"term": {"classe.codigo": 1116}} in must
    assert {"match_phrase": {"assuntos.nome": "Dano Moral"}} in must


def test_data_fora_do_formato_iso_e_recusada():
    with pytest.raises(filtros.FiltroInvalido, match="AAAA-MM-DD"):
        filtros.montar_filtros(data_inicio="31/01/2024")


def test_intervalo_cobre_as_duas_formas_da_base():
    # Regressão: parte dos tribunais grava dataAjuizamento como o número
    # yyyyMMddHHmmss, que o Elasticsearch lê como epoch em milissegundos
    # — um processo de 2019 cai no ano 2610. Um filtro só em ISO perdia
    # esses registros, e em alguns tribunais isso é o acervo inteiro.
    must = filtros.montar_filtros(data_inicio="2024-01-01", data_fim="2024-12-31")
    assert len(must) == 1
    should = must[0]["bool"]["should"]
    assert {
        "range": {"dataAjuizamento": {"gte": "2024-01-01", "lte": "2024-12-31"}}
    } in should
    assert {
        "range": {"dataAjuizamento": {"gte": 20240101000000, "lte": 20241231235959}}
    } in should
    assert must[0]["bool"]["minimum_should_match"] == 1


def test_agregacao_por_ano_usa_buckets_explicitos():
    # date_histogram devolveria "2610" para processos de 2019.
    corpo = filtros.montar_agregacao("ano", [], tamanho=5)
    chaves = corpo["aggs"]["grupos"]["filters"]["filters"]
    assert all(k.isdigit() and len(k) == 4 for k in chaves)
    assert all("bool" in v for v in chaves.values())


def test_buckets_nomeados_da_agregacao_por_ano():
    resposta = {
        "aggregations": {
            "grupos": {"buckets": {"2023": {"doc_count": 7}, "2024": {"doc_count": 9}}}
        }
    }
    assert resumo.extrair_buckets(resposta, "ano") == [
        {"valor": "2023", "quantidade": 7},
        {"valor": "2024", "quantidade": 9},
    ]


def test_busca_sem_filtro_usa_match_all():
    assert filtros.montar_busca([])["query"] == {"match_all": {}}


def test_tamanho_de_pagina_e_limitado():
    assert filtros.montar_busca([], tamanho=99999)["size"] == 1000
    assert filtros.montar_busca([], tamanho=0)["size"] == 1


def test_agregacao_embute_documento_de_exemplo():
    corpo = filtros.montar_agregacao("assunto", [])
    assert "exemplo" in corpo["aggs"]["grupos"]["aggs"]


def test_agrupamento_invalido_lista_as_opcoes():
    with pytest.raises(filtros.FiltroInvalido, match="classe"):
        filtros.montar_agregacao("juiz", [])


# -------------------------------------------------------------------- resumo


PROCESSO = {
    "numeroProcesso": "00000010220248170001",
    "tribunal": "TJPE",
    "grau": "G1",
    "dataAjuizamento": "2024-03-15T00:00:00.000Z",
    "classe": {"codigo": 1116, "nome": "Execução Fiscal"},
    "orgaoJulgador": {
        "codigo": 1,
        "nome": "1ª Vara",
        "codigoMunicipioIBGE": 2611606,
    },
    "assuntos": [
        {"codigo": 5952, "nome": "IPTU"},
        {"codigo": 6017, "nome": "Dívida Ativa"},
    ],
    "movimentos": [
        {"codigo": 26, "nome": "Distribuição", "dataHora": "2024-03-15T09:00:00Z"},
        {"codigo": 51, "nome": "Conclusão", "dataHora": "2024-06-01T14:00:00Z"},
        {"codigo": 60, "nome": "Expedição", "dataHora": "2024-04-02T10:00:00Z"},
    ],
}


def test_resumo_pega_o_movimento_cronologicamente_mais_recente():
    # A API não devolve os movimentos ordenados; o mais recente aqui é
    # o segundo do vetor original, não o último.
    r = resumo.resumir_processo(PROCESSO)
    assert r["ultimoMovimento"]["nome"] == "Conclusão"
    assert r["qtdMovimentos"] == 3


def test_resumo_formata_o_numero_do_processo():
    r = resumo.resumir_processo(PROCESSO)
    assert r["numeroProcesso"] == "0000001-02.2024.8.17.0001"


def test_resumo_de_processo_sem_movimentos():
    r = resumo.resumir_processo({"numeroProcesso": "0" * 20})
    assert r["ultimoMovimento"] is None
    assert r["qtdMovimentos"] == 0


def test_linha_do_tempo_respeita_ordem_e_limite():
    linha = resumo.resumir_movimentos(PROCESSO, limite=2)
    assert linha["totalMovimentos"] == 3
    assert linha["exibindo"] == 2
    assert [m["nome"] for m in linha["movimentos"]] == ["Conclusão", "Expedição"]


def test_rotulagem_de_assunto_usa_o_codigo_correto():
    # Regressão do bug de rotulagem: com dois assuntos no mesmo
    # processo, o rótulo do código 6017 não pode virar "IPTU".
    resposta = {
        "aggregations": {
            "grupos": {
                "buckets": [{
                    "key": 6017,
                    "doc_count": 10,
                    "exemplo": {"hits": {"hits": [{"_source": PROCESSO}]}},
                }]
            }
        }
    }
    grupos = resumo.extrair_buckets(resposta, "assunto")
    assert grupos == [{"valor": 6017, "quantidade": 10, "nome": "Dívida Ativa"}]


def test_resposta_de_busca_expoe_cursor_de_paginacao():
    resposta = {
        "hits": {
            "total": {"value": 42, "relation": "eq"},
            "hits": [{"_source": PROCESSO, "sort": [123456789]}],
        }
    }
    r = resumo.resumir_resposta(resposta)
    assert r["total"] == 42
    assert r["totalExato"] is True
    assert r["proximaPagina"] == [123456789]


def test_total_aproximado_e_sinalizado():
    resposta = {"hits": {"total": {"value": 10000, "relation": "gte"}, "hits": []}}
    assert resumo.resumir_resposta(resposta)["totalExato"] is False


# ---------------------------------------------------------- contra a API real


@pytest.mark.rede
def test_todos_os_aliases_respondem():
    """Detecta renomeação de índice pelo CNJ em qualquer um dos 91."""
    import time

    from datajud_mcp.cliente import ClienteDataJud, ErroDataJud

    corpo = {"size": 0, "query": {"match_all": {}}}
    falhas = []
    with ClienteDataJud() as cliente:
        for sigla in tribunais.TRIBUNAIS:
            try:
                cliente.consultar(sigla, corpo)
            except ErroDataJud as e:
                falhas.append(f"{sigla}: {e}")
            time.sleep(0.1)
    assert not falhas, "Aliases quebrados: " + "; ".join(falhas)


@pytest.mark.rede
def test_consulta_por_numero_encontra_processo_conhecido():
    from datajud_mcp.cliente import ClienteDataJud

    with ClienteDataJud() as cliente:
        resposta = cliente.consultar(
            "TRF5", filtros.montar_por_numero("00018980720234058103")
        )
    assert resposta["hits"]["total"]["value"] >= 1


@pytest.mark.rede
def test_agregacao_rotula_assunto_com_o_nome_certo():
    """Regressão do bug de rotulagem, contra dados reais."""
    from datajud_mcp.cliente import ClienteDataJud

    with ClienteDataJud() as cliente:
        resposta = cliente.consultar(
            "TJPE", filtros.montar_agregacao("assunto", [], tamanho=5)
        )
    grupos = resumo.extrair_buckets(resposta, "assunto")
    assert grupos, "a agregação não devolveu grupos"
    # Cada grupo precisa ter um nome, e nomes distintos para códigos
    # distintos — era exatamente isso que a sub-agregação embaralhava.
    nomes = [g["nome"] for g in grupos if "nome" in g]
    assert len(nomes) == len(grupos)
    assert len(set(nomes)) == len(nomes)

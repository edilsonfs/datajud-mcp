"""Servidor MCP do DataJud: as ferramentas que o modelo enxerga.

O desenho das ferramentas segue uma regra: quem pergunta é advogado,
estudante ou servidor — não engenheiro de dados. Então ninguém precisa
saber sigla de tribunal (o número do processo já diz qual é), nem código
da Tabela Processual Unificada (há uma ferramenta que descobre), nem
sintaxe de Elasticsearch (fica disponível, mas só para quem quiser).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, numero_cnj
from .cliente import ClienteDataJud, ErroDataJud
from .filtros import (
    CAMPOS_AGRUPAVEIS,
    FiltroInvalido,
    montar_agregacao,
    montar_amostra_para_codigos,
    montar_busca,
    montar_contagem,
    montar_filtros,
    montar_por_numero,
)
from .resumo import (
    extrair_buckets,
    resumir_movimentos,
    resumir_processo,
    resumir_resposta,
)
from .tribunais import TRIBUNAIS, obter
from .tribunais import buscar as buscar_tribunais

AVISO_COBERTURA = (
    "A API DataJud publica apenas metadados processuais. Não há nomes de "
    "partes ou advogados, nem teor de decisões, petições ou sentenças."
)

URL_FONTE = "https://datajud-wiki.cnj.jus.br/api-publica/acesso"

mcp = MCPServer(
    "datajud",
    title="DataJud — processos judiciais brasileiros",
    version=__version__,
    website_url="https://github.com/edilsonfs/datajud-mcp",
    instructions=(
        "Consulta de processos judiciais brasileiros pela API Pública "
        "DataJud do CNJ, cobrindo 91 tribunais.\n\n"
        "Como decidir a ferramenta:\n"
        "- O usuário deu um número de processo? Use consultar_processo. "
        "Não peça a sigla do tribunal: ela é deduzida do próprio número.\n"
        "- Quer a movimentação/andamento? Use movimentacoes_processo.\n"
        "- Quer volume ('quantos processos de...')? Use contar_processos.\n"
        "- Quer ranking ou distribuição ('quais as classes mais comuns', "
        "'quais varas julgam mais')? Use estatisticas.\n"
        "- Precisa do código de uma classe ou assunto da TPU? Use "
        "descobrir_codigos antes de filtrar por código.\n\n"
        f"{AVISO_COBERTURA}"
    ),
)

_cliente = ClienteDataJud()


def _erro(mensagem: str, **extras: Any) -> dict[str, Any]:
    return {"erro": mensagem, **extras}


def _fonte_do_primeiro(resposta: dict[str, Any]) -> dict[str, Any] | None:
    hits = (resposta.get("hits", {}) or {}).get("hits", []) or []
    return hits[0].get("_source", {}) if hits else None


def _localizar(
    numero: str,
    tribunal: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Encontra um processo, deduzindo o tribunal quando não informado.

    Devolve ``(documento, diagnóstico)``. O diagnóstico registra onde se
    procurou, para que o modelo possa explicar um resultado vazio em vez
    de apenas dizer "não encontrei".
    """
    limpo = numero_cnj.limpar(numero)
    analise = numero_cnj.analisar(limpo)
    diagnostico: dict[str, Any] = {"numeroConsultado": numero_cnj.formatar(limpo)}

    if tribunal:
        candidatos = [tribunal]
    elif analise and analise.tribunais:
        candidatos = analise.tribunais
        diagnostico["tribunalDeduzido"] = candidatos
    else:
        return None, _erro(
            "Não foi possível deduzir o tribunal a partir do número. "
            "Informe a sigla no parâmetro tribunal (ex: TJSP, TRF5, TRT6).",
            **diagnostico,
        )

    if analise and not analise.valido:
        diagnostico["avisoDigitoVerificador"] = (
            "O dígito verificador não confere — o número pode ter sido "
            "digitado errado. A busca foi feita mesmo assim."
        )

    tentados: list[str] = []
    for sigla in candidatos:
        try:
            resposta = _cliente.consultar(sigla, montar_por_numero(limpo, tamanho=1))
        except ErroDataJud as e:
            tentados.append(f"{sigla} (erro: {e})")
            continue
        tentados.append(sigla)
        fonte = _fonte_do_primeiro(resposta)
        if fonte:
            diagnostico["tribunal"] = sigla
            return fonte, diagnostico

    diagnostico["tribunaisConsultados"] = tentados
    return None, diagnostico


@mcp.tool()
def listar_tribunais(filtro: str = "") -> dict[str, Any]:
    """Lista os 91 tribunais consultáveis, opcionalmente filtrados.

    Args:
        filtro: texto livre para restringir a lista — sigla ("TJ"),
            estado ("Pernambuco"), ou ramo ("Justiça do Trabalho").
            Vazio devolve todos, agrupados por ramo de Justiça.
    """
    encontrados = buscar_tribunais(filtro)
    if not encontrados:
        return _erro(
            f"Nenhum tribunal corresponde a '{filtro}'. "
            "Tente pelo estado (ex: 'Bahia') ou pelo ramo "
            "(ex: 'Justiça Eleitoral')."
        )

    grupos: dict[str, list[dict[str, str]]] = {}
    for t in encontrados:
        grupos.setdefault(t.justica, []).append({"sigla": t.sigla, "nome": t.nome})
    for lista in grupos.values():
        lista.sort(key=lambda x: x["sigla"])

    return {"total": len(encontrados), "grupos": grupos}


@mcp.tool()
def identificar_processo(numero_processo: str) -> dict[str, Any]:
    """Decifra um número de processo sem consultar a API.

    Diz o ano, o ramo de Justiça, o tribunal e a unidade de origem, e
    confere o dígito verificador. Serve para orientar o usuário antes de
    qualquer busca — inclusive para detectar número digitado errado.

    Args:
        numero_processo: número CNJ, com ou sem máscara.
    """
    analise = numero_cnj.analisar(numero_processo)
    if analise is None:
        achados = numero_cnj.extrair(numero_processo)
        if not achados:
            return _erro(
                "O número informado não tem os 20 dígitos do padrão CNJ "
                "(NNNNNNN-DD.AAAA.J.TR.OOOO). Confira se algum dígito "
                "ficou faltando."
            )
        analise = numero_cnj.analisar(achados[0])
    if analise is None:
        return _erro("Não foi possível interpretar o número informado.")

    saida: dict[str, Any] = {
        "numero": analise.formatado,
        "ano": analise.ano,
        "ramoDeJustica": analise.justica,
        "unidadeDeOrigem": analise.origem,
        "digitoVerificadorConfere": analise.valido,
        "tribunaisParaConsulta": analise.tribunais,
    }
    if not analise.valido:
        esperado = numero_cnj.calcular_digito(analise.numero)
        saida["aviso"] = (
            f"O dígito verificador informado é {analise.digito_verificador}, "
            f"mas o cálculo oficial resulta em {esperado}. Provável erro de "
            "digitação."
        )
    elif not analise.tribunais:
        saida["aviso"] = (
            f"O segmento {analise.segmento} ({analise.justica}) não é "
            "coberto pela API DataJud."
        )
    return saida


@mcp.tool()
def consultar_processo(
    numero_processo: str,
    tribunal: str = "",
    detalhe_completo: bool = False,
) -> dict[str, Any]:
    """Consulta um processo pelo número, deduzindo o tribunal.

    É a ferramenta a usar quando o usuário simplesmente cola um número.
    Não peça a sigla do tribunal antes de tentar: ela está codificada no
    próprio número.

    Args:
        numero_processo: número CNJ, com ou sem máscara.
        tribunal: sigla, apenas se quiser forçar um tribunal específico.
        detalhe_completo: ``True`` devolve o documento bruto inteiro,
            com todos os movimentos. Pode ser muito extenso — prefira
            movimentacoes_processo.
    """
    fonte, diagnostico = _localizar(numero_processo, tribunal or None)
    if fonte is None:
        if "erro" in diagnostico:
            return diagnostico
        return _erro(
            "Processo não encontrado. Isso pode significar que ele "
            "tramita em segredo de justiça, que ainda não foi enviado ao "
            "DataJud, ou que o número está incorreto.",
            **diagnostico,
        )

    if detalhe_completo:
        return {**diagnostico, "processo": fonte}
    return {**diagnostico, "processo": resumir_processo(fonte)}


@mcp.tool()
def movimentacoes_processo(
    numero_processo: str,
    tribunal: str = "",
    limite: int = 30,
    mais_recentes_primeiro: bool = True,
) -> dict[str, Any]:
    """Devolve a linha do tempo de andamentos de um processo.

    Args:
        numero_processo: número CNJ, com ou sem máscara.
        tribunal: sigla, apenas para forçar um tribunal específico.
        limite: quantos movimentos trazer (1-500). Padrão: 30.
        mais_recentes_primeiro: ordem da linha do tempo.
    """
    fonte, diagnostico = _localizar(numero_processo, tribunal or None)
    if fonte is None:
        if "erro" in diagnostico:
            return diagnostico
        return _erro("Processo não encontrado.", **diagnostico)

    linha = resumir_movimentos(
        fonte, limite=limite, ordem_decrescente=mais_recentes_primeiro
    )
    linha["observacao"] = (
        "Os movimentos seguem a Tabela de Movimentos do CNJ e são "
        "genéricos por natureza. Não incluem o teor das decisões."
    )
    return {**diagnostico, **linha}


@mcp.tool()
def buscar_processos(
    tribunal: str,
    nome_classe: str = "",
    codigo_classe: int | None = None,
    nome_assunto: str = "",
    codigo_assunto: int | None = None,
    nome_orgao: str = "",
    codigo_orgao: int | None = None,
    codigo_municipio_ibge: int | None = None,
    grau: str = "",
    data_inicio: str = "",
    data_fim: str = "",
    tamanho: int = 20,
    search_after: list[Any] | None = None,
) -> dict[str, Any]:
    """Busca processos combinando qualquer conjunto de filtros.

    Todos os filtros são opcionais e se somam (E lógico). Se não souber
    o código de uma classe ou assunto, use descobrir_codigos primeiro,
    ou informe o nome — a busca por nome exige as palavras na ordem
    digitada, mas ignora maiúsculas e acentos.

    Args:
        tribunal: sigla (ex: TJPE, TRF5, TRT6, TRESP, STJ).
        nome_classe: ex. "Execução Fiscal", "Apelação Cível".
        codigo_classe: código da classe na TPU.
        nome_assunto: ex. "Indenização por Dano Moral".
        codigo_assunto: código do assunto na TPU.
        nome_orgao: ex. "1ª Vara Cível", "Juizado Especial".
        codigo_orgao: código do órgão julgador.
        codigo_municipio_ibge: restringe à comarca do município
            (ex: 2611606 = Recife, 3550308 = São Paulo).
        grau: "G1" (primeiro grau), "G2" (segundo grau), "JE" (juizado).
        data_inicio: ajuizamento a partir de (AAAA-MM-DD).
        data_fim: ajuizamento até (AAAA-MM-DD).
        tamanho: resultados por página (1-1000). Padrão: 20.
        search_after: valor de proximaPagina, para a página seguinte.
    """
    try:
        must = montar_filtros(
            codigo_classe=codigo_classe,
            nome_classe=nome_classe or None,
            codigo_assunto=codigo_assunto,
            nome_assunto=nome_assunto or None,
            codigo_orgao=codigo_orgao,
            nome_orgao=nome_orgao or None,
            codigo_municipio_ibge=codigo_municipio_ibge,
            grau=grau or None,
            data_inicio=data_inicio or None,
            data_fim=data_fim or None,
        )
    except FiltroInvalido as e:
        return _erro(str(e))

    if not must:
        return _erro(
            "Informe ao menos um filtro. Sem filtro a busca devolveria o "
            "acervo inteiro do tribunal — use contar_processos se o que "
            "você quer é o total."
        )

    try:
        resposta = _cliente.consultar(
            tribunal, montar_busca(must, tamanho=tamanho, search_after=search_after)
        )
    except ErroDataJud as e:
        return _erro(str(e))

    trib = obter(tribunal)
    resultado = resumir_resposta(resposta)
    resultado["tribunal"] = trib.sigla if trib else tribunal.upper()
    return resultado


@mcp.tool()
def contar_processos(
    tribunal: str,
    nome_classe: str = "",
    codigo_classe: int | None = None,
    nome_assunto: str = "",
    codigo_assunto: int | None = None,
    nome_orgao: str = "",
    codigo_orgao: int | None = None,
    codigo_municipio_ibge: int | None = None,
    grau: str = "",
    data_inicio: str = "",
    data_fim: str = "",
) -> dict[str, Any]:
    """Conta processos sem trazer os documentos — rápido e barato.

    Use para responder "quantos processos de X existem em Y" e para
    conferir a volumetria antes de uma extração grande.

    Aceita os mesmos filtros de buscar_processos, todos opcionais.
    Sem nenhum filtro, devolve o acervo total do tribunal.
    """
    try:
        must = montar_filtros(
            codigo_classe=codigo_classe,
            nome_classe=nome_classe or None,
            codigo_assunto=codigo_assunto,
            nome_assunto=nome_assunto or None,
            codigo_orgao=codigo_orgao,
            nome_orgao=nome_orgao or None,
            codigo_municipio_ibge=codigo_municipio_ibge,
            grau=grau or None,
            data_inicio=data_inicio or None,
            data_fim=data_fim or None,
        )
    except FiltroInvalido as e:
        return _erro(str(e))

    try:
        resposta = _cliente.consultar(tribunal, montar_contagem(must))
    except ErroDataJud as e:
        return _erro(str(e))

    trib = obter(tribunal)
    total = (resposta.get("hits", {}) or {}).get("total", {}) or {}
    return {
        "tribunal": trib.sigla if trib else tribunal.upper(),
        "nomeTribunal": trib.nome if trib else None,
        "total": total.get("value", 0),
        "filtrosAplicados": len(must),
    }


@mcp.tool()
def estatisticas(
    tribunal: str,
    agrupar_por: str,
    nome_classe: str = "",
    codigo_classe: int | None = None,
    nome_assunto: str = "",
    codigo_assunto: int | None = None,
    nome_orgao: str = "",
    codigo_municipio_ibge: int | None = None,
    grau: str = "",
    data_inicio: str = "",
    data_fim: str = "",
    tamanho: int = 30,
) -> dict[str, Any]:
    """Agrupa o acervo e devolve as contagens — o "raio-X" do tribunal.

    Responde perguntas de distribuição: quais classes mais aparecem,
    quais varas concentram o acervo, como a entrada evoluiu por ano.

    Args:
        tribunal: sigla.
        agrupar_por: "classe", "assunto", "orgao", "grau", "formato",
            "sistema" ou "ano".
        tamanho: quantos grupos retornar (1-200). Padrão: 30.
        demais parâmetros: os mesmos filtros de buscar_processos.
    """
    try:
        must = montar_filtros(
            codigo_classe=codigo_classe,
            nome_classe=nome_classe or None,
            codigo_assunto=codigo_assunto,
            nome_assunto=nome_assunto or None,
            nome_orgao=nome_orgao or None,
            codigo_municipio_ibge=codigo_municipio_ibge,
            grau=grau or None,
            data_inicio=data_inicio or None,
            data_fim=data_fim or None,
        )
        corpo = montar_agregacao(agrupar_por, must, tamanho=tamanho)
    except FiltroInvalido as e:
        return _erro(str(e), agrupamentosValidos=list(CAMPOS_AGRUPAVEIS))

    try:
        resposta = _cliente.consultar(tribunal, corpo)
    except ErroDataJud as e:
        return _erro(str(e))

    trib = obter(tribunal)
    return {
        "tribunal": trib.sigla if trib else tribunal.upper(),
        "agrupadoPor": agrupar_por,
        "totalProcessosNoRecorte": (
            (resposta.get("hits", {}) or {}).get("total", {}) or {}
        ).get("value", 0),
        "grupos": extrair_buckets(resposta, agrupar_por),
    }


@mcp.tool()
def descobrir_codigos(
    tribunal: str,
    tipo: str,
    termo: str,
    tamanho_amostra: int = 100,
) -> dict[str, Any]:
    """Descobre códigos da Tabela Processual Unificada a partir de um termo.

    Resolve o maior atrito de quem não trabalha com dados do Judiciário:
    saber que "Execução Fiscal" é a classe 1116. Busca uma amostra real
    de processos do tribunal e extrai os pares código/nome que casam com
    o termo.

    Args:
        tribunal: sigla — os códigos são nacionais, mas a amostra vem
            deste tribunal.
        tipo: "classe" ou "assunto".
        termo: parte do nome (ex: "fiscal", "dano moral", "usucapião").
        tamanho_amostra: processos examinados (1-200). Padrão: 100.
    """
    tipo = tipo.strip().lower()
    if tipo not in ("classe", "assunto"):
        return _erro("tipo deve ser 'classe' ou 'assunto'.")

    campo = "classe.nome" if tipo == "classe" else "assuntos.nome"
    try:
        resposta = _cliente.consultar(
            tribunal, montar_amostra_para_codigos(campo, termo, tamanho_amostra)
        )
    except ErroDataJud as e:
        return _erro(str(e))

    alvo = termo.strip().lower()
    contagem: dict[int, dict[str, Any]] = {}
    for hit in (resposta.get("hits", {}) or {}).get("hits", []) or []:
        fonte = hit.get("_source", {}) or {}
        itens = (
            [fonte.get("classe")] if tipo == "classe"
            else (fonte.get("assuntos") or [])
        )
        for item in itens:
            if not isinstance(item, dict):
                continue
            codigo, nome = item.get("codigo"), item.get("nome")
            if codigo is None or not nome or alvo not in nome.lower():
                continue
            registro = contagem.setdefault(
                codigo,
                {"codigo": codigo, "nome": nome, "ocorrenciasNaAmostra": 0},
            )
            registro["ocorrenciasNaAmostra"] += 1

    achados = sorted(
        contagem.values(), key=lambda x: x["ocorrenciasNaAmostra"], reverse=True
    )
    if not achados:
        return _erro(
            f"Nenhum(a) {tipo} contendo '{termo}' apareceu na amostra. "
            "Tente um termo mais curto ou uma grafia diferente — a "
            "nomenclatura oficial pode diferir do uso corrente.",
            tribunal=tribunal.upper(),
        )

    return {
        "tribunal": tribunal.upper(),
        "tipo": tipo,
        "termo": termo,
        "encontrados": achados,
        "comoUsar": (
            f"Passe o código escolhido em codigo_{tipo} nas ferramentas "
            "buscar_processos, contar_processos ou estatisticas."
        ),
    }


@mcp.tool()
def consulta_avancada(tribunal: str, query_json: str) -> dict[str, Any]:
    """Executa uma consulta Elasticsearch DSL bruta — para uso avançado.

    Só é necessária para combinações que as demais ferramentas não
    cobrem: ``should``/``must_not``, agregações aninhadas, percentis.

    Args:
        tribunal: sigla.
        query_json: corpo completo da requisição, em JSON.
            Documentação: https://datajud-wiki.cnj.jus.br/api-publica/exemplos
    """
    try:
        corpo = json.loads(query_json)
    except json.JSONDecodeError as e:
        return _erro(f"JSON inválido: {e}")
    if not isinstance(corpo, dict):
        return _erro("O JSON deve ser um objeto com o corpo da consulta.")

    try:
        return _cliente.consultar(tribunal, corpo)
    except ErroDataJud as e:
        return _erro(str(e))


# --- Compatibilidade com o Deep Research da OpenAI -------------------
# O modo de pesquisa profunda do ChatGPT exige, por contrato, duas
# ferramentas chamadas "search" e "fetch". Mantê-las aqui faz o servidor
# funcionar nesse modo sem prejudicar as ferramentas em português.

@mcp.tool()
def search(query: str) -> dict[str, Any]:
    """Busca processos a partir de texto livre (compatível com Deep Research).

    Aceita um número de processo, ou uma sigla de tribunal seguida do que
    se procura — por exemplo "TJPE execução fiscal".

    Args:
        query: número CNJ ou "SIGLA termo de busca".
    """
    numeros = numero_cnj.extrair(query)
    if numeros:
        fonte, diagnostico = _localizar(numeros[0], None)
        if fonte is None:
            return {"results": []}
        sigla = diagnostico.get("tribunal", "")
        resumo = resumir_processo(fonte)
        titulo = (resumo.get("classe") or {}).get("nome") or "Processo"
        return {
            "results": [{
                "id": f"{sigla}:{numero_cnj.limpar(numeros[0])}",
                "title": f"{resumo['numeroProcesso']} — {titulo} ({sigla})",
                "url": URL_FONTE,
            }]
        }

    partes = query.split()
    achado = next(((p, obter(p)) for p in partes if obter(p) is not None), None)
    if achado is None:
        return {
            "results": [],
            "aviso": (
                "Informe a sigla do tribunal na consulta "
                "(ex: 'TJSP usucapião') ou um número de processo."
            ),
        }

    texto_sigla, trib = achado
    termo = " ".join(p for p in partes if p != texto_sigla).strip()
    if not termo:
        return {"results": [], "aviso": "Informe também o que buscar."}

    must = montar_filtros(nome_assunto=termo)
    try:
        resposta = _cliente.consultar(trib.sigla, montar_busca(must, tamanho=10))
    except ErroDataJud as e:
        return {"results": [], "erro": str(e)}

    resultados = []
    for p in resumir_resposta(resposta)["processos"]:
        titulo = (p.get("classe") or {}).get("nome") or "Processo"
        resultados.append({
            "id": f"{trib.sigla}:{numero_cnj.limpar(p['numeroProcesso'])}",
            "title": f"{p['numeroProcesso']} — {titulo}",
            "url": URL_FONTE,
        })
    return {"results": resultados}


@mcp.tool()
def fetch(id: str) -> dict[str, Any]:
    """Recupera um processo pelo identificador devolvido por search.

    Args:
        id: no formato "SIGLA:numero" (ex: "TJPE:00012345620248170001").
    """
    sigla, _, numero = id.partition(":")
    if not numero:
        numero, sigla = sigla, ""

    fonte, _diagnostico = _localizar(numero, sigla or None)
    if fonte is None:
        return _erro(f"Processo '{id}' não encontrado.")

    resumo = resumir_processo(fonte)
    linha = resumir_movimentos(fonte, limite=50)
    linhas = [
        f"Processo {resumo['numeroProcesso']} ({resumo['tribunal']})",
        f"Classe: {(resumo['classe'] or {}).get('nome')}",
        f"Órgão julgador: {(resumo['orgaoJulgador'] or {}).get('nome')}",
        f"Ajuizamento: {resumo['dataAjuizamento']}",
        f"Grau: {resumo['grau']}",
        "Assuntos: " + ", ".join(
            a.get("nome") or "" for a in resumo["assuntos"]
        ),
        "",
        f"Movimentos ({linha['totalMovimentos']} no total, "
        f"{linha['exibindo']} exibidos):",
    ]
    for m in linha["movimentos"]:
        linhas.append(f"  {m.get('dataHora')} — {m.get('nome')}")

    return {
        "id": id,
        "title": f"{resumo['numeroProcesso']} — {resumo['tribunal']}",
        "text": "\n".join(linhas),
        "url": URL_FONTE,
        "metadata": {"fonte": "API Pública DataJud/CNJ", "aviso": AVISO_COBERTURA},
    }


# --- Roteiros prontos ------------------------------------------------

@mcp.prompt()
def raio_x_do_tribunal(tribunal: str, ano: str = "") -> str:
    """Roteiro para levantar o perfil de acervo de um tribunal."""
    recorte = f" no ano de {ano}" if ano else ""
    return (
        f"Levante o perfil do acervo do {tribunal}{recorte} usando o "
        "servidor DataJud. Faça nesta ordem:\n"
        "1. contar_processos para o total do recorte.\n"
        "2. estatisticas agrupando por 'classe' (top 15).\n"
        "3. estatisticas agrupando por 'assunto' (top 15).\n"
        "4. estatisticas agrupando por 'orgao' (top 15).\n"
        "5. estatisticas agrupando por 'ano', para ver a evolução.\n"
        "Apresente em tabelas e feche com três observações sobre o que "
        "concentra o acervo. Registre que os dados são metadados "
        "públicos do DataJud/CNJ."
    )


@mcp.prompt()
def situacao_do_processo(numero_processo: str) -> str:
    """Roteiro para explicar a situação de um processo a um leigo."""
    return (
        f"Explique a situação do processo {numero_processo}:\n"
        "1. identificar_processo, para conferir o número e o tribunal.\n"
        "2. consultar_processo, para classe, assunto, vara e data.\n"
        "3. movimentacoes_processo (limite 20), para o andamento.\n"
        "Escreva para quem não é da área: diga em que fase o processo "
        "parece estar e o que os últimos movimentos indicam. Deixe claro "
        "que a movimentação é genérica e não revela o teor das decisões."
    )


@mcp.prompt()
def comparar_tribunais(assunto: str, tribunais: str) -> str:
    """Roteiro para comparar o mesmo assunto entre tribunais."""
    return (
        f"Compare o volume de processos sobre '{assunto}' entre os "
        f"tribunais: {tribunais}.\n"
        "1. descobrir_codigos (tipo 'assunto') no primeiro tribunal para "
        "achar o código correto.\n"
        "2. contar_processos com esse código em cada tribunal.\n"
        "3. estatisticas por 'ano' em cada um, para ver a tendência.\n"
        "Monte uma tabela comparativa e alerte que os tribunais têm "
        "portes e práticas de cadastro diferentes, o que limita a "
        "comparação direta."
    )


# --- Rota de saúde -------------------------------------------------
# Usada pelo HEALTHCHECK do contêiner e pelo balanceador quando o
# servidor roda hospedado. Fica fora do protocolo MCP e não exige
# autorização — por isso não revela nada além do próprio estado.

@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_request: Any) -> Any:
    from starlette.responses import JSONResponse

    return JSONResponse({
        "status": "ok",
        "servico": "datajud-mcp",
        "versao": __version__,
        "tribunais": len(TRIBUNAIS),
    })


def main() -> None:
    """Ponto de entrada do console script ``datajud-mcp``."""
    mcp.run()


if __name__ == "__main__":
    main()

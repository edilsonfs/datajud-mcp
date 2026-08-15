"""Painel web das unidades judiciárias, servido pelo próprio servidor.

Consulta a API DataJud a cada interação — não há banco intermediário nem
cache, então o que aparece na tela é o estado atual da base do CNJ.

As cinco agregações que compõem uma visualização são disparadas em
paralelo: sequencialmente a página levaria cinco viagens de rede até o
CNJ, e a espera acumulada é o que faz um painel parecer quebrado.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .cliente import ClienteDataJud, ErroDataJud
from .filtros import montar_agregacao, montar_busca, montar_contagem, montar_filtros
from .resumo import extrair_buckets, resumir_resposta
from .tribunais import TRIBUNAIS, obter


def _agregar(
    cliente: ClienteDataJud,
    tribunal: str,
    agrupar_por: str,
    must: list[dict[str, Any]],
    tamanho: int,
) -> list[dict[str, Any]]:
    resposta = cliente.consultar(
        tribunal, montar_agregacao(agrupar_por, must, tamanho=tamanho)
    )
    return extrair_buckets(resposta, agrupar_por)


def coletar(
    cliente: ClienteDataJud,
    tribunal: str,
    ano: str = "",
    grau: str = "",
    codigo_orgao: int | None = None,
    codigo_assunto: int | None = None,
    codigo_classe: int | None = None,
) -> dict[str, Any]:
    """Reúne, em tempo real, o retrato de um recorte do acervo.

    O gráfico de evolução por ano ignora de propósito o filtro de ano —
    é ele que dá o contexto para o recorte selecionado fazer sentido.
    """
    trib = obter(tribunal)
    if trib is None:
        raise ErroDataJud(f"Tribunal '{tribunal}' não reconhecido.")

    comuns: dict[str, Any] = {
        "grau": grau or None,
        "codigo_orgao": codigo_orgao,
        "codigo_assunto": codigo_assunto,
        "codigo_classe": codigo_classe,
    }
    if ano:
        must = montar_filtros(
            data_inicio=f"{ano}-01-01", data_fim=f"{ano}-12-31", **comuns
        )
    else:
        must = montar_filtros(**comuns)
    must_sem_ano = montar_filtros(**comuns)

    with ThreadPoolExecutor(max_workers=5) as executor:
        f_total = executor.submit(cliente.consultar, trib.sigla, montar_contagem(must))
        f_unidades = executor.submit(_agregar, cliente, trib.sigla, "orgao", must, 25)
        f_classes = executor.submit(_agregar, cliente, trib.sigla, "classe", must, 10)
        f_assuntos = executor.submit(_agregar, cliente, trib.sigla, "assunto", must, 10)
        f_anos = executor.submit(_agregar, cliente, trib.sigla, "ano", must_sem_ano, 30)

        resposta_total = f_total.result()
        unidades = f_unidades.result()
        classes = f_classes.result()
        assuntos = f_assuntos.result()
        anos = f_anos.result()

    total = ((resposta_total.get("hits", {}) or {}).get("total", {}) or {}).get(
        "value", 0
    )

    anos = [b for b in anos if b.get("quantidade")]

    # A série cobre de 2000 ao ano corrente. O que sobra do total são
    # processos anteriores a isso ou com data de ajuizamento ilegível —
    # é informação sobre a base, e some se não for dita.
    na_serie = sum(b.get("quantidade", 0) for b in anos)
    fora_da_serie = max(0, total - na_serie) if not ano else 0

    return {
        "tribunal": {"sigla": trib.sigla, "nome": trib.nome, "justica": trib.justica},
        "filtros": {"ano": ano, "grau": grau, "orgao": codigo_orgao},
        "total": total,
        "unidades": unidades,
        "classes": classes,
        "assuntos": assuntos,
        "anos": anos,
        "foraDaSerie": {
            "quantidade": fora_da_serie,
            "primeiroAno": anos[0]["valor"] if anos else None,
        },
    }


def listar_processos(
    cliente: ClienteDataJud,
    tribunal: str,
    ano: str = "",
    grau: str = "",
    codigo_orgao: int | None = None,
    codigo_assunto: int | None = None,
    codigo_classe: int | None = None,
    tamanho: int = 25,
    search_after: list[Any] | None = None,
) -> dict[str, Any]:
    """Lista os processos de um recorte, um a um, com paginação.

    É o que permite sair da estatística e olhar os autos que a
    compõem — ver *quais* processos formam aquele assunto, e não apenas
    quantos.
    """
    trib = obter(tribunal)
    if trib is None:
        raise ErroDataJud(f"Tribunal '{tribunal}' não reconhecido.")

    must = montar_filtros(
        grau=grau or None,
        codigo_orgao=codigo_orgao,
        codigo_assunto=codigo_assunto,
        codigo_classe=codigo_classe,
        **(
            {"data_inicio": f"{ano}-01-01", "data_fim": f"{ano}-12-31"}
            if ano
            else {}
        ),
    )
    resposta = cliente.consultar(
        trib.sigla,
        montar_busca(must, tamanho=tamanho, search_after=search_after),
    )
    resultado = resumir_resposta(resposta)
    resultado["tribunal"] = trib.sigla
    return resultado


def lista_tribunais() -> list[dict[str, str]]:
    """Catálogo para o seletor, agrupado por ramo de Justiça."""
    return [
        {"sigla": t.sigla, "nome": t.nome, "justica": t.justica}
        for t in sorted(TRIBUNAIS.values(), key=lambda t: (t.justica, t.sigla))
    ]


# ---------------------------------------------------------------------
# A página. Autocontida de propósito: sem CDN, sem build, uma requisição.
# ---------------------------------------------------------------------

PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel das Unidades Judiciárias — DataJud</title>
<meta name="description" content="Acervo das unidades judiciárias dos 91 tribunais brasileiros, consultado em tempo real na API Publica DataJud do CNJ.">
<style>
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --plane: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --s1: #2a78d6;
  --s2: #eb6834;
  --s3: #1baf7a;
  --wash: #cde2fb;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --s1: #3987e5;
    --s2: #d95926;
    --s3: #199e70;
    --wash: #184f95;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --plane: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --s1: #3987e5;
  --s2: #d95926;
  --s3: #199e70;
  --wash: #184f95;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--plane);
  color: var(--text-primary);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 24px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--text-secondary); font-size: 14px; margin: 0; }
.sub a { color: inherit; }

.filtros {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
  margin: 18px 0 16px; padding: 14px;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
}
.campo { display: flex; flex-direction: column; gap: 4px; }
.campo label { font-size: 12px; color: var(--muted); }
select, button {
  font: inherit; padding: 7px 10px; border-radius: 7px;
  border: 1px solid var(--axis); background: var(--surface-1); color: var(--text-primary);
}
select { max-width: 320px; }
button { cursor: pointer; border-color: var(--s1); color: var(--s1); font-weight: 600; }
button:hover { background: var(--wash); }
button.limpar { border-color: var(--axis); color: var(--text-secondary); font-weight: 400; }
.recorte { display: none; align-items: center; gap: 8px; font-size: 13px;
  color: var(--text-secondary); margin-bottom: 14px; flex-wrap: wrap; }
.recorte.on { display: flex; }
.chip { display: inline-block; background: var(--surface-1); border: 1px solid var(--s1);
  color: var(--s1); border-radius: 999px; padding: 3px 10px; font-weight: 600;
  cursor: pointer; margin: 2px 3px 2px 0; max-width: 380px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.chip:hover { background: var(--wash); }
td.mono { font-variant-numeric: tabular-nums; white-space: nowrap; }
.sutil { color: var(--muted); font-size: 11.5px; }
button.mais { margin-top: 12px; width: 100%; }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr)); gap: 12px; margin-bottom: 16px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile .rot { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.tile .val { font-size: 30px; font-weight: 650; margin-top: 4px; letter-spacing: -0.02em; }
.tile .nota { font-size: 12px; color: var(--text-secondary); margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.cards { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 900px) { .duplo { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; } }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.card h2 { font-size: 15px; margin: 0 0 2px; }
.card .cap { font-size: 12.5px; color: var(--text-secondary); margin: 0 0 14px; }

.barras { display: flex; flex-direction: column; gap: 7px; }
.linha { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center;
  padding: 3px; margin: -3px; border-radius: 6px; }
.rotulo { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.valor { font-size: 13px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.trilho { grid-column: 1 / -1; height: 9px; background: var(--grid); border-radius: 4px; overflow: hidden; }
.preenche { height: 100%; border-radius: 4px; }
.clicavel { cursor: pointer; }
.clicavel:hover { background: var(--grid); }
.linha.sel { background: var(--grid); outline: 2px solid var(--s1); }

.colunas { display: flex; align-items: flex-end; gap: 4px; min-height: 200px; }
.col { flex: 1; display: flex; flex-direction: column; justify-content: flex-end;
  align-items: center; gap: 5px; min-width: 0; }
.col .haste { width: 100%; background: var(--s1); border-radius: 4px 4px 0 0; min-height: 2px; }
.col .ano { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums;
  writing-mode: vertical-rl; transform: rotate(180deg); }
.col .qtd { font-size: 10.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }

table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--grid); }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.rolagem { overflow-x: auto; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--text-secondary); font-size: 13px; }

.aviso { color: var(--critical); font-size: 13.5px; padding: 10px 0; }
.nota-dados { font-size: 12.5px; color: var(--text-secondary); margin: 14px 0 0;
  padding: 10px 12px; background: var(--grid); border-radius: 8px; line-height: 1.55; }
.carregando { color: var(--muted); font-size: 13.5px; padding: 30px 0; text-align: center; }
.vazio { color: var(--muted); font-size: 13px; padding: 12px 0; }
footer { margin-top: 30px; color: var(--muted); font-size: 12.5px; line-height: 1.7; }
footer a { color: var(--text-secondary); }
.pulse { animation: p 1.2s ease-in-out infinite; }
@keyframes p { 0%,100% { opacity: 1 } 50% { opacity: .45 } }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Painel das Unidades Judiciarias</h1>
  <p class="sub">Acervo dos 91 tribunais brasileiros, consultado ao vivo na
     <a href="https://datajud-wiki.cnj.jus.br/api-publica/acesso" target="_blank" rel="noopener">API Publica DataJud</a> do CNJ.</p>
</header>

<div class="filtros">
  <div class="campo">
    <label for="f-trib">Tribunal</label>
    <select id="f-trib"></select>
  </div>
  <div class="campo">
    <label for="f-ano">Ano de ajuizamento</label>
    <select id="f-ano"><option value="">Todos</option></select>
  </div>
  <div class="campo">
    <label for="f-grau">Grau</label>
    <select id="f-grau">
      <option value="">Todos</option>
      <option value="G1">1o grau</option>
      <option value="G2">2o grau</option>
      <option value="JE">Juizado especial</option>
      <option value="TR">Turma recursal</option>
    </select>
  </div>
  <button id="b-atualizar">Consultar</button>
</div>

<div class="recorte" id="recorte">
  <span>Recorte ativo:</span>
  <span id="chips"></span>
  <button class="limpar" id="b-limpar">limpar tudo</button>
</div>

<div id="conteudo"></div>

<footer>
  Dados: API Publica DataJud/CNJ &mdash; metadados processuais publicos
  (Resolucao CNJ no 331/2020). Nao inclui partes, advogados nem teor de decisoes.
  Processos em segredo de justica nao aparecem, e a base reflete a ultima carga
  enviada por cada tribunal.<br>
  Codigo aberto: <a href="https://github.com/edilsonfs/datajud-mcp" target="_blank" rel="noopener">github.com/edilsonfs/datajud-mcp</a>
</footer>
</div>

<script>
const $ = (s) => document.querySelector(s);
const conteudo = $("#conteudo");
const nf = new Intl.NumberFormat("pt-BR");

// Recorte ativo. Cada dimensao guarda codigo e nome: o codigo vai para
// a consulta, o nome aparece no chip.
const recorte = { orgao: null, assunto: null, classe: null };
const ROTULO = { orgao: "Unidade", assunto: "Assunto", classe: "Classe" };
let cursor = null, processosCarregados = [], totalProcessos = 0;

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const compacto = (n) => n >= 1e6 ? (n/1e6).toFixed(1).replace(".",",")+"M"
                     : n >= 1e3 ? Math.round(n/1e3)+"k" : String(n);
const soData = (s) => {
  if (!s) return "\\u2014";
  const m = String(s).match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
  return m ? m[3] + "/" + m[2] + "/" + m[1] : String(s).slice(0, 10);
};

function barras(itens, corVar, dimensao) {
  if (!itens.length) return '<p class="vazio">Sem resultados neste recorte.</p>';
  const max = Math.max.apply(null, itens.map(i => i.quantidade)) || 1;
  return '<div class="barras">' + itens.map(function (i) {
    const nome = i.nome || ("Codigo " + i.valor);
    const pct = Math.max(1, (i.quantidade / max) * 100);
    const ativo = dimensao && recorte[dimensao] &&
                  String(recorte[dimensao].codigo) === String(i.valor);
    const attr = dimensao
      ? ' data-dim="' + dimensao + '" data-codigo="' + i.valor + '" data-nome="' + esc(nome) + '"'
      : "";
    return '<div class="linha' + (dimensao ? " clicavel" : "") + (ativo ? " sel" : "") + '"' + attr +
           ' title="' + esc(nome) + ' \\u2014 ' + nf.format(i.quantidade) + ' processos' +
           (dimensao ? ' (clique para recortar)' : '') + '">' +
           '<span class="rotulo">' + esc(nome) + '</span>' +
           '<span class="valor">' + nf.format(i.quantidade) + '</span>' +
           '<span class="trilho"><span class="preenche" style="width:' + pct + '%;background:var(' + corVar + ')"></span></span>' +
           '</div>';
  }).join("") + '</div>';
}

function colunas(anos) {
  if (!anos.length) return '<p class="vazio">Sem serie historica.</p>';
  const max = Math.max.apply(null, anos.map(a => a.quantidade)) || 1;
  return '<div class="colunas">' + anos.map(a =>
    '<div class="col" title="' + a.valor + ' \\u2014 ' + nf.format(a.quantidade) + ' processos">' +
      '<span class="qtd">' + compacto(a.quantidade) + '</span>' +
      '<span class="haste" style="height:' + Math.max(2, (a.quantidade / max) * 140) + 'px"></span>' +
      '<span class="ano">' + a.valor + '</span>' +
    '</div>').join("") + '</div>';
}

// O que a serie nao alcanca e dito, nao escondido.
function notaAnos(fora) {
  if (!fora || !fora.quantidade) return "";
  return '<p class="nota-dados"><strong>' + nf.format(fora.quantidade) +
         '</strong> processos do recorte estao fora do grafico: foram ajuizados antes de ' +
         esc(fora.primeiroAno || "2000") + ' ou tem data de ajuizamento ilegivel na base do CNJ.</p>';
}

function tabela(unidades) {
  const tot = unidades.reduce((s,x) => s + x.quantidade, 0) || 1;
  return '<div class="rolagem"><table><thead><tr>' +
    '<th>Unidade judiciaria</th><th class="num">Codigo</th><th class="num">Processos</th><th class="num">% do exibido</th>' +
    '</tr></thead><tbody>' + unidades.map(u =>
      '<tr><td>' + esc(u.nome || "\\u2014") + '</td><td class="num">' + u.valor +
      '</td><td class="num">' + nf.format(u.quantidade) +
      '</td><td class="num">' + ((u.quantidade/tot)*100).toFixed(1).replace(".",",") + '%</td></tr>'
    ).join("") + '</tbody></table></div>';
}

const tile = (rot, val, nota) =>
  '<div class="tile"><div class="rot">' + rot + '</div><div class="val">' + val +
  '</div><div class="nota" title="' + esc(nota) + '">' + esc(nota) + '</div></div>';
const card = (t, cap, corpo, id) =>
  '<section class="card"' + (id ? ' id="' + id + '"' : '') + '><h2>' + t + '</h2>' +
  '<p class="cap">' + cap + '</p>' + corpo + '</section>';

function render(d) {
  const topo = d.unidades[0];
  conteudo.innerHTML =
    '<div class="tiles">' +
      tile("Processos no recorte", nf.format(d.total), d.tribunal.sigla + " \\u00b7 " + d.tribunal.justica) +
      tile("Unidades exibidas", nf.format(d.unidades.length), "as de maior acervo") +
      tile("Maior acervo", topo ? compacto(topo.quantidade) : "\\u2014", topo ? (topo.nome || "\\u2014") : "sem dados") +
    '</div>' +
    '<div class="cards">' +
      card("Unidades judiciarias por acervo",
           "Clique em uma unidade para recortar todo o painel por ela.",
           barras(d.unidades, "--s1", "orgao") +
           '<details><summary>Ver como tabela</summary>' + tabela(d.unidades) + '</details>') +
      '<div class="duplo">' +
        card("Classes processuais", "Clique para recortar por classe.", barras(d.classes, "--s2", "classe")) +
        card("Assuntos", "Clique para recortar por assunto.", barras(d.assuntos, "--s3", "assunto")) +
      '</div>' +
      card("Ajuizamentos por ano",
           "Serie completa do recorte \\u2014 nao e afetada pelo filtro de ano.",
           colunas(d.anos) + notaAnos(d.foraDaSerie)) +
      card("Processos do recorte",
           "Os autos que formam os numeros acima. Metadados publicos apenas.",
           '<div id="lista-processos"><p class="vazio">Carregando processos\\u2026</p></div>',
           "card-processos") +
    '</div>';

  conteudo.querySelectorAll(".linha[data-dim]").forEach(function (el) {
    el.addEventListener("click", function () {
      const dim = el.getAttribute("data-dim");
      const cod = el.getAttribute("data-codigo");
      const jaAtivo = recorte[dim] && String(recorte[dim].codigo) === String(cod);
      recorte[dim] = jaAtivo ? null : { codigo: cod, nome: el.getAttribute("data-nome") || "" };
      atualizarChips();
      consultar();
    });
  });

  carregarProcessos(true);
}

function linhasProcessos(itens) {
  return itens.map(function (p) {
    const assuntos = (p.assuntos || []).map(a => a.nome).filter(Boolean).join("; ");
    const mov = p.ultimoMovimento || {};
    return '<tr>' +
      '<td class="mono">' + esc(p.numeroProcesso || "\\u2014") + '</td>' +
      '<td>' + esc((p.classe || {}).nome || "\\u2014") + '</td>' +
      '<td>' + esc(assuntos || "\\u2014") + '</td>' +
      '<td>' + esc((p.orgaoJulgador || {}).nome || "\\u2014") + '</td>' +
      '<td class="num">' + soData(p.dataAjuizamento) + '</td>' +
      '<td>' + esc(mov.nome || "\\u2014") + '<br><span class="sutil">' + soData(mov.dataHora) + '</span></td>' +
      '</tr>';
  }).join("");
}

function pintarProcessos(temMais) {
  const alvo = $("#lista-processos");
  if (!alvo) return;
  if (!processosCarregados.length) {
    alvo.innerHTML = '<p class="vazio">Nenhum processo encontrado neste recorte.</p>';
    return;
  }
  alvo.innerHTML =
    '<p class="cap">Exibindo <strong>' + nf.format(processosCarregados.length) +
    '</strong> de ' + nf.format(totalProcessos) + ' processos.</p>' +
    '<div class="rolagem"><table><thead><tr>' +
    '<th>Numero</th><th>Classe</th><th>Assuntos</th><th>Unidade</th>' +
    '<th class="num">Ajuizamento</th><th>Ultimo movimento</th>' +
    '</tr></thead><tbody>' + linhasProcessos(processosCarregados) + '</tbody></table></div>' +
    (temMais ? '<button id="b-mais" class="mais">Carregar mais 25</button>' : '');
  const b = $("#b-mais");
  if (b) b.addEventListener("click", function () { carregarProcessos(false); });
}

async function carregarProcessos(reiniciar) {
  if (reiniciar) { cursor = null; processosCarregados = []; }
  const alvo = $("#lista-processos");
  const botao = alvo ? alvo.querySelector("#b-mais") : null;
  if (botao) botao.textContent = "Carregando\\u2026";
  const p = parametros();
  if (cursor) p.set("cursor", JSON.stringify(cursor));
  try {
    const r = await fetch("/api/processos?" + p.toString());
    const d = await r.json();
    if (d.erro) { if (alvo) alvo.innerHTML = '<p class="aviso">' + esc(d.erro) + '</p>'; return; }
    processosCarregados = processosCarregados.concat(d.processos || []);
    totalProcessos = d.total || 0;
    cursor = d.proximaPagina || null;
    pintarProcessos(Boolean(cursor) && processosCarregados.length < totalProcessos);
  } catch (e) {
    if (alvo) alvo.innerHTML = '<p class="aviso">Nao foi possivel listar os processos.</p>';
  }
}

function atualizarChips() {
  const caixa = $("#recorte");
  const ativos = Object.keys(recorte).filter(k => recorte[k]);
  if (!ativos.length) { caixa.classList.remove("on"); return; }
  caixa.classList.add("on");
  $("#chips").innerHTML = ativos.map(k =>
    '<span class="chip" data-dim="' + k + '" title="Remover este recorte">' +
    ROTULO[k] + ": " + esc(recorte[k].nome) + ' \\u00d7</span>'
  ).join(" ");
  $("#chips").querySelectorAll(".chip").forEach(function (c) {
    c.addEventListener("click", function () {
      recorte[c.getAttribute("data-dim")] = null;
      atualizarChips();
      consultar();
    });
  });
}

function parametros() {
  const p = new URLSearchParams({
    tribunal: $("#f-trib").value,
    ano: $("#f-ano").value,
    grau: $("#f-grau").value
  });
  Object.keys(recorte).forEach(function (k) {
    if (recorte[k]) p.set(k, recorte[k].codigo);
  });
  return p;
}

async function consultar() {
  conteudo.innerHTML = '<p class="carregando pulse">Consultando a base do CNJ\\u2026</p>';
  try {
    const r = await fetch("/api/painel?" + parametros().toString());
    const d = await r.json();
    if (d.erro) { conteudo.innerHTML = '<p class="aviso">' + esc(d.erro) + '</p>'; return; }
    render(d);
  } catch (e) {
    conteudo.innerHTML = '<p class="aviso">Nao foi possivel consultar a API do CNJ. Tente novamente em instantes.</p>';
  }
}

function limparTudo() {
  Object.keys(recorte).forEach(k => recorte[k] = null);
  atualizarChips();
  consultar();
}

async function iniciar() {
  const anoAtual = new Date().getFullYear();
  const selAno = $("#f-ano");
  for (let a = anoAtual; a >= 2000; a--) {
    selAno.insertAdjacentHTML("beforeend", '<option value="' + a + '">' + a + '</option>');
  }
  const tribs = await (await fetch("/api/tribunais")).json();
  const sel = $("#f-trib");
  let grupo = "";
  tribs.forEach(function (t) {
    if (t.justica !== grupo) { grupo = t.justica; sel.insertAdjacentHTML("beforeend", '<optgroup label="' + esc(grupo) + '">'); }
    sel.insertAdjacentHTML("beforeend", '<option value="' + t.sigla + '">' + t.sigla + ' \\u2014 ' + esc(t.nome) + '</option>');
  });
  sel.value = "TJPE";
  sel.addEventListener("change", limparTudo);
  $("#f-ano").addEventListener("change", consultar);
  $("#f-grau").addEventListener("change", consultar);
  $("#b-atualizar").addEventListener("click", consultar);
  $("#b-limpar").addEventListener("click", limparTudo);
  consultar();
}
iniciar();
</script>
</body>
</html>
"""

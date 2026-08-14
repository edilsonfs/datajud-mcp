# DataJud MCP

**Converse com os dados de 91 tribunais brasileiros.** Este servidor conecta seu assistente de IA — Claude, ChatGPT ou Gemini — à [API Pública DataJud](https://datajud-wiki.cnj.jus.br/api-publica/acesso) do Conselho Nacional de Justiça.

Você pergunta em português. O assistente consulta os dados oficiais e responde.

> **"Em que pé está o processo 0008265-72.2018.4.05.8300?"**
>
> **"Quantas execuções fiscais o TJPE tem em Recife?"**
>
> **"Quais as 10 varas com maior acervo no TJSP?"**
>
> **"Compare processos sobre dano moral entre TJPE, TJBA e TJCE."**

Não é preciso saber a sigla do tribunal — ela está codificada no número do processo, e o servidor a descobre sozinho. Também não é preciso decorar códigos da Tabela Processual Unificada: há uma ferramenta que os encontra a partir do nome.

---

## Índice

- [O que dá e o que não dá para consultar](#o-que-dá-e-o-que-não-dá-para-consultar)
- [Instalação (5 minutos)](#instalação-5-minutos)
- [Passo a passo: Claude Desktop](#passo-a-passo-claude-desktop)
- [Passo a passo: Claude Code](#passo-a-passo-claude-code)
- [Passo a passo: ChatGPT](#passo-a-passo-chatgpt)
- [Passo a passo: Gemini](#passo-a-passo-gemini)
- [Ferramentas disponíveis](#ferramentas-disponíveis)
- [Exemplos de perguntas](#exemplos-de-perguntas)
- [Solução de problemas](#solução-de-problemas)
- [Para desenvolvedores](#para-desenvolvedores)

---

## O que dá e o que não dá para consultar

O DataJud é a base nacional de **metadados** processuais. Isso define exatamente o que este servidor entrega.

| ✅ Disponível | ❌ Não disponível |
|---|---|
| Número, classe e assuntos do processo | Nomes de partes e advogados |
| Vara/órgão julgador e comarca | Teor de decisões, sentenças e acórdãos |
| Data de ajuizamento e grau | Petições e documentos |
| Linha do tempo de movimentações (códigos CNJ) | Valor da causa |
| Volumetria e estatísticas de acervo | Jurisprudência |

Para o conteúdo dos autos, use o PJe, o e-SAJ ou o portal do tribunal. Este servidor serve para **localizar processos, acompanhar andamentos e analisar acervos**.

> [!IMPORTANT]
> Processos em segredo de justiça não aparecem. A base é alimentada pelos tribunais com periodicidade variável, então pode haver atraso de dias em relação ao sistema processual de origem.

---

## Instalação (5 minutos)

Você precisa de **Python 3.10 ou superior**. Para conferir, abra o terminal e digite `python --version`.

<details>
<summary><b>Não tenho Python instalado</b></summary>

- **Windows**: baixe em [python.org/downloads](https://www.python.org/downloads/) e marque **"Add Python to PATH"** durante a instalação.
- **macOS**: `brew install python` (ou baixe de python.org).
- **Linux**: já vem instalado na maioria das distribuições.
</details>

Com o Python pronto, instale o servidor:

```bash
pip install datajud-mcp
```

Confira se funcionou:

```bash
datajud-mcp --version
```

Se aparecer um número de versão, está pronto. Agora escolha sua plataforma abaixo.

---

## Passo a passo: Claude Desktop

**1.** Abra o Claude Desktop e vá em **Configurações → Desenvolvedor → Editar configuração**.

Isso abre o arquivo `claude_desktop_config.json`. Se preferir abrir na mão:

| Sistema | Caminho |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

**2.** Cole este conteúdo no arquivo (se já houver outros servidores, acrescente apenas o bloco `"datajud"` dentro de `mcpServers`):

```json
{
  "mcpServers": {
    "datajud": {
      "command": "datajud-mcp"
    }
  }
}
```

**3.** Salve e **feche o Claude Desktop por completo** (no Windows, verifique também a bandeja do sistema). Abra de novo.

**4.** Confirme: clique no ícone de ferramentas na caixa de mensagem. Deve aparecer **datajud** com 11 ferramentas.

**5.** Teste perguntando: *"Quantos processos o TJPE tem no total?"*

<details>
<summary><b>Se der erro "command not found"</b></summary>

O Claude Desktop pode não enxergar o `PATH` do seu terminal. Use o caminho completo do Python:

```json
{
  "mcpServers": {
    "datajud": {
      "command": "python",
      "args": ["-m", "datajud_mcp"]
    }
  }
}
```

Se ainda falhar, descubra o caminho exato do Python com `where python` (Windows) ou `which python3` (macOS/Linux) e use-o no lugar de `"python"`.
</details>

---

## Passo a passo: Claude Code

Um comando só:

```bash
claude mcp add datajud datajud-mcp
```

Confira com `claude mcp list`. Para usar em todos os projetos, acrescente `--scope user`:

```bash
claude mcp add datajud datajud-mcp --scope user
```

---

## Passo a passo: ChatGPT

O ChatGPT conecta a servidores MCP **pela internet**, não a programas instalados na sua máquina. São duas etapas: publicar o servidor em um endereço acessível e conectá-lo.

**1.** Suba o servidor em modo HTTP:

```bash
datajud-mcp --transport http --host 0.0.0.0 --port 8000
```

Para um teste rápido sem hospedagem própria, exponha sua máquina com um túnel:

```bash
npx localtunnel --port 8000
```

Anote a URL gerada e acrescente `/mcp` ao final.

> [!WARNING]
> Um túnel deixa o servidor acessível a qualquer pessoa com o link. Use apenas para testes e derrube-o depois. Para uso contínuo, hospede em um servidor próprio com HTTPS.

**2.** No ChatGPT, vá em **Configurações → Conectores → Criar** (o recurso exige plano pago e, em algumas contas, ativar o **modo desenvolvedor** em Configurações → Conectores → Avançado).

**3.** Informe:
- **Nome**: DataJud
- **URL do servidor MCP**: a URL do passo 1, terminando em `/mcp`
- **Autenticação**: nenhuma

**4.** Salve e ative o conector na conversa, pelo menu **+ → Mais → Conectores**.

O servidor inclui as ferramentas `search` e `fetch` no padrão exigido pela OpenAI, então também funciona no modo **Deep Research**.

---

## Passo a passo: Gemini

### Gemini CLI (recomendado)

Instale a CLI, se ainda não tiver:

```bash
npm install -g @google/gemini-cli
```

Edite `~/.gemini/settings.json` (no Windows, `%USERPROFILE%\.gemini\settings.json`):

```json
{
  "mcpServers": {
    "datajud": {
      "command": "datajud-mcp"
    }
  }
}
```

Rode `gemini` e digite `/mcp` para confirmar que o servidor apareceu.

### API do Gemini (para quem desenvolve)

Suba o servidor em modo HTTP e aponte o SDK para ele — o SDK do Gemini chama ferramentas MCP diretamente. Veja [ai.google.dev/gemini-api/docs/function-calling](https://ai.google.dev/gemini-api/docs/function-calling).

> [!NOTE]
> O aplicativo web do Gemini ainda não aceita servidores MCP de terceiros. Use a CLI ou a API.

---

## Ferramentas disponíveis

| Ferramenta | Para que serve |
|---|---|
| `consultar_processo` | Dados de um processo pelo número. **Descobre o tribunal sozinho.** |
| `movimentacoes_processo` | Linha do tempo dos andamentos. |
| `identificar_processo` | Decifra o número (ano, tribunal, vara) e confere o dígito verificador — sem consultar a API. |
| `contar_processos` | Quantos processos existem em um recorte. Rápido. |
| `buscar_processos` | Lista processos combinando filtros, com paginação. |
| `estatisticas` | Agrupa o acervo por classe, assunto, órgão, grau, formato, sistema ou ano. |
| `descobrir_codigos` | Encontra o código da TPU a partir do nome ("execução fiscal" → 1116). |
| `listar_tribunais` | Os 91 tribunais e suas siglas. |
| `consulta_avancada` | Elasticsearch DSL bruto, para casos que as demais não cobrem. |
| `search` / `fetch` | Compatibilidade com o Deep Research do ChatGPT. |

E três roteiros prontos (prompts MCP): `raio_x_do_tribunal`, `situacao_do_processo` e `comparar_tribunais`.

---

## Exemplos de perguntas

**Acompanhamento processual**
- "Em que pé está o processo 0008265-72.2018.4.05.8300?"
- "Mostre os últimos 10 andamentos desse processo."
- "Esse número está correto? 0000001-02.2024.8.17.0001"

**Análise de acervo**
- "Quais as 15 classes processuais mais frequentes no TJBA em 2024?"
- "Quais varas de Recife concentram mais execuções fiscais?"
- "Como evoluiu a entrada de processos no TRT6 desde 2019?"

**Pesquisa comparada**
- "Compare o volume de processos sobre dano moral entre TJPE, TJBA e TJCE."
- "Qual a proporção de processos eletrônicos e físicos no TJMG?"

**Descoberta**
- "Qual o código da classe 'usucapião'?"
- "Que assuntos existem relacionados a 'improbidade'?"

---

## Solução de problemas

**O servidor não aparece no Claude Desktop.**
Feche o aplicativo por inteiro (inclusive na bandeja do sistema) e reabra. Confirme que `datajud-mcp --version` funciona no terminal. Se não funcionar, use a forma com `python -m datajud_mcp` mostrada acima.

**"Processo não encontrado" para um número que existe.**
Três causas prováveis: segredo de justiça, atraso do tribunal no envio ao DataJud, ou erro de digitação. Peça ao assistente para usar `identificar_processo` — ele confere o dígito verificador e aponta erro de digitação.

**"A API do CNJ recusou por excesso de requisições."**
Limite da API pública. Espere alguns segundos e repita. Em análises grandes, peça páginas menores.

**"A API do CNJ recusou a chave de acesso."**
A chave pública do CNJ foi rotacionada. Pegue a nova em [datajud-wiki.cnj.jus.br/api-publica/acesso](https://datajud-wiki.cnj.jus.br/api-publica/acesso) e defina a variável de ambiente:

```json
{
  "mcpServers": {
    "datajud": {
      "command": "datajud-mcp",
      "env": { "DATAJUD_API_KEY": "sua-chave-aqui" }
    }
  }
}
```

**Os números não batem com o sistema do tribunal.**
São bases distintas. O DataJud recebe cargas periódicas dos tribunais e reflete o que foi enviado, não o estado em tempo real.

---

## Para desenvolvedores

```bash
git clone https://github.com/edilsonfs/datajud-mcp
cd datajud-mcp
pip install -e ".[dev]"

pytest -m "not rede"    # testes unitários, sem rede
pytest -m rede          # valida os 91 aliases contra a API real
ruff check .
```

Inspecionar as ferramentas sem cliente MCP:

```bash
npx @modelcontextprotocol/inspector datajud-mcp
```

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DATAJUD_API_KEY` | chave pública do CNJ | Sobrescreve a chave de acesso. |
| `DATAJUD_TIMEOUT` | `45` | Tempo limite das requisições, em segundos. |

### Arquitetura

```
tribunais.py   catálogo dos 91 tribunais (alias, segmento CNJ, nome)
numero_cnj.py  leitura e validação do número único de processo
cliente.py     HTTP com repetição exponencial em 429/5xx
filtros.py     construção das consultas Elasticsearch
resumo.py      redução das respostas ao que cabe no contexto do modelo
server.py      as ferramentas MCP
```

Contribuições são bem-vindas. Abra uma issue antes de mudanças grandes.

---

## Licença e uso dos dados

Código sob licença [MIT](LICENSE).

Os dados vêm da API Pública DataJud do CNJ, regida pela [Resolução CNJ nº 331/2020](https://atos.cnj.jus.br/atos/detalhar/3428) e pela Portaria CNJ nº 160/2020. São metadados processuais públicos.

Ao usar estes dados, respeite a Lei Geral de Proteção de Dados. Trabalhos acadêmicos devem citar o CNJ como fonte. Este projeto não tem vínculo com o Conselho Nacional de Justiça.

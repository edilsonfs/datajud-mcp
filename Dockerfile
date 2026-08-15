# Imagem do servidor DataJud MCP em modo remoto (Streamable HTTP).
#
# É esta imagem que permite usar o servidor sem instalar nada na
# máquina do usuário — inclusive no ChatGPT, que só conecta a
# servidores MCP acessíveis pela internet.

FROM python:3.12-slim

# Copiar metadados antes do código: assim uma mudança em src/ não
# invalida a camada de instalação de dependências.
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 datajud

# O servidor não grava nada em disco e não precisa de privilégios.
USER datajud

ENV DATAJUD_MCP_HOST=0.0.0.0 \
    DATAJUD_MCP_PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status==200 else 1)"

CMD ["sh", "-c", "datajud-mcp --transport http --host ${DATAJUD_MCP_HOST} --port ${DATAJUD_MCP_PORT}"]

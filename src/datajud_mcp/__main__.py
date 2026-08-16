"""Ponto de entrada do servidor.

Padrão é ``stdio``, que é como Claude Desktop, Claude Code e Gemini CLI
iniciam servidores MCP locais. O transporte HTTP existe para quando o
servidor for hospedado e compartilhado com quem não quer instalar nada.
"""

from __future__ import annotations

import argparse

from . import __version__


# Cabeçalhos de segurança exigidos pelo OWASP ZAP (CSP, anti-clickjacking,
# HSTS, nosniff). O painel (painel.py) é autocontido, com <script>/<style>
# inline e sem CDN — por isso script-src/style-src toleram 'unsafe-inline';
# todo o resto fica preso a 'self'. Aplicados via wrapper ASGI para cobrir
# tanto o painel quanto as rotas /api e o próprio protocolo MCP.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)
_HEADERS_SEGURANCA = [
    (b"content-security-policy", _CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]


def _com_headers_seguranca(app):
    """Envolve um app ASGI acrescentando os cabeçalhos de segurança às respostas HTTP."""

    async def wrapper(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        async def send_com_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                presentes = {k.lower() for k, _ in headers}
                for chave, valor in _HEADERS_SEGURANCA:
                    if chave not in presentes:
                        headers.append((chave, valor))
            await send(message)

        await app(scope, receive, send_com_headers)

    return wrapper


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="datajud-mcp",
        description=(
            "Servidor MCP da API Pública DataJud/CNJ — consulta de "
            "processos judiciais dos 91 tribunais brasileiros."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio (padrão, para clientes locais) ou http (servidor remoto).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host do modo http.")
    parser.add_argument("--port", type=int, default=8000, help="Porta do modo http.")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    # Importado aqui para que --help e --version não paguem o custo de
    # subir o servidor nem de abrir a conexão HTTP com a API.
    from .server import mcp

    if args.transport == "http":
        import uvicorn

        app = _com_headers_seguranca(mcp.streamable_http_app())
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()

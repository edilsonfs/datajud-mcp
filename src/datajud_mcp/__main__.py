"""Ponto de entrada do servidor.

Padrão é ``stdio``, que é como Claude Desktop, Claude Code e Gemini CLI
iniciam servidores MCP locais. O transporte HTTP existe para quando o
servidor for hospedado e compartilhado com quem não quer instalar nada.
"""

from __future__ import annotations

import argparse

from . import __version__


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
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()

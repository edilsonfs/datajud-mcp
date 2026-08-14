"""Cliente HTTP da API Pública DataJud, com repetição automática.

A API do CNJ aplica limite de requisições e ocasionalmente devolve 5xx
sob carga. Sem repetição, uma extração longa morre no meio — por isso o
cliente distingue os erros que adianta repetir (429 e 5xx) daqueles que
não adiantam (400, 401, 404), e usa espera exponencial nos primeiros.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

import httpx

from .tribunais import obter

# Chave pública divulgada pelo CNJ no wiki oficial da API. Não é
# credencial pessoal: é a mesma para todos os consumidores. Fica aqui
# para que o servidor funcione sem configuração, e pode ser trocada por
# DATAJUD_API_KEY caso o CNJ a rotacione.
CHAVE_PUBLICA_CNJ = (
    "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
)
URL_BASE = "https://api-publica.datajud.cnj.jus.br"

STATUS_REPETIVEIS = {429, 500, 502, 503, 504}


class ErroDataJud(RuntimeError):
    """Falha ao consultar a API DataJud, com mensagem para o usuário final."""

    def __init__(self, mensagem: str, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


class TribunalDesconhecido(ErroDataJud):
    """A sigla informada não corresponde a nenhum tribunal do DataJud."""


class ClienteDataJud:
    """Envia consultas Elasticsearch para o índice de um tribunal."""

    def __init__(
        self,
        chave_api: str | None = None,
        timeout: float | None = None,
        tentativas: int = 4,
    ):
        chave = (
            chave_api
            or os.environ.get("DATAJUD_API_KEY")
            or CHAVE_PUBLICA_CNJ
        )
        if timeout is None:
            timeout = float(os.environ.get("DATAJUD_TIMEOUT", "45"))
        self.tentativas = max(1, tentativas)
        self._http = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"APIKey {chave}",
                "Content-Type": "application/json",
                "User-Agent": (
                    "datajud-mcp (https://github.com/edilsonfs/datajud-mcp)"
                ),
            },
        )

    def fechar(self) -> None:
        self._http.close()

    def __enter__(self) -> ClienteDataJud:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.fechar()

    def consultar(self, tribunal: str, corpo: dict[str, Any]) -> dict[str, Any]:
        """Executa uma consulta no índice do tribunal e devolve o JSON bruto.

        Args:
            tribunal: sigla como ``TJPE``, ``TRT6``, ``TRESP``.
            corpo: corpo da requisição em Elasticsearch DSL.

        Raises:
            TribunalDesconhecido: sigla não reconhecida.
            ErroDataJud: falha de rede ou resposta de erro da API.
        """
        trib = obter(tribunal)
        if trib is None:
            raise TribunalDesconhecido(
                f"Tribunal '{tribunal}' não reconhecido. "
                "Use a ferramenta listar_tribunais para ver as 91 siglas "
                "aceitas (exemplos: TJPE, TJSP, TRF5, TRT6, TRESP, STJ)."
            )

        url = f"{URL_BASE}/{trib.alias}/_search"
        ultimo_erro: str = ""
        ultimo_status: int | None = None

        for tentativa in range(self.tentativas):
            try:
                resposta = self._http.post(url, json=corpo)
            except httpx.HTTPError as e:
                ultimo_erro = f"falha de rede: {e}"
                ultimo_status = None
            else:
                if resposta.status_code == 200:
                    return resposta.json()
                ultimo_status = resposta.status_code
                ultimo_erro = resposta.text[:400]
                if resposta.status_code not in STATUS_REPETIVEIS:
                    break

            if tentativa < self.tentativas - 1:
                # Espera exponencial com ruído, para não sincronizar
                # repetições de vários clientes contra a mesma API.
                time.sleep((2 ** tentativa) + random.uniform(0, 0.5))

        raise ErroDataJud(
            self._mensagem_amigavel(ultimo_status, ultimo_erro, trib.sigla),
            status=ultimo_status,
        )

    @staticmethod
    def _mensagem_amigavel(status: int | None, detalhe: str, sigla: str) -> str:
        if status == 429:
            return (
                "A API do CNJ recusou por excesso de requisições (429). "
                "Aguarde alguns segundos e tente de novo, ou reduza o "
                "tamanho da página."
            )
        if status in (401, 403):
            return (
                "A API do CNJ recusou a chave de acesso. A chave pública "
                "pode ter sido rotacionada — consulte "
                "https://datajud-wiki.cnj.jus.br/api-publica/acesso e "
                "defina a variável de ambiente DATAJUD_API_KEY."
            )
        if status == 404:
            return (
                f"O índice do tribunal {sigla} não foi encontrado na API. "
                "Isso costuma indicar que o CNJ renomeou o índice."
            )
        if status == 400:
            return f"A API rejeitou a consulta (400). Detalhe: {detalhe}"
        if status is None:
            return (
                f"Não foi possível falar com a API do CNJ ({detalhe}). "
                "Verifique a conexão de rede."
            )
        return f"A API do CNJ devolveu HTTP {status}. Detalhe: {detalhe}"

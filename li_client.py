import time
import logging
from typing import Dict, Any, List, Optional
import requests
from config import (
    LI_BASE_URL,
    LI_PERSONAL_TOKEN,
    LI_CHAVE_API,
    LI_CHAVE_APLICACAO,
    LI_REQUEST_DELAY,
)
from db import upsert_product_from_li

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LojaIntegradaClient")


class LojaIntegradaClient:
    """
    Cliente para integração com a API v1 da Loja Integrada.
    Gerencia autenticação (Personal Token ou chave_api/aplicacao),
    rate limiting, retentativas automáticas e sincronização com SQLite.
    """

    def __init__(self):
        self.base_url = LI_BASE_URL
        self.session = requests.Session()
        self.headers = self._build_auth_headers()
        self.session.headers.update(self.headers)

    def _build_auth_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if LI_PERSONAL_TOKEN:
            token = LI_PERSONAL_TOKEN
            if not token.startswith("Basic ") and not token.startswith("Bearer "):
                token = f"Basic {token}"
            headers["Authorization"] = token
        elif LI_CHAVE_API and LI_CHAVE_APLICACAO:
            headers["Authorization"] = f"chave_api {LI_CHAVE_API} aplicacao {LI_CHAVE_APLICACAO}"
        else:
            raise ValueError("Nenhuma credencial de autenticação da Loja Integrada configurada no .env.")
        return headers

    def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Executa requisição HTTP respeitando rate limits da Loja Integrada (100 req/min).
        Possui retry automático com backoff exponencial se receber 429 ou erro 633.
        """
        # Normaliza o endpoint
        clean_endpoint = endpoint.strip()
        if clean_endpoint.startswith("/api/v1/"):
            clean_endpoint = clean_endpoint[len("/api/v1/"):]
        elif clean_endpoint.startswith("/v1/"):
            clean_endpoint = clean_endpoint[len("/v1/"):]
        elif clean_endpoint.startswith("/"):
            clean_endpoint = clean_endpoint[1:]

        url = f"{self.base_url}/{clean_endpoint}"
        max_retries = 4
        base_delay = 5.0

        for attempt in range(1, max_retries + 1):
            time.sleep(LI_REQUEST_DELAY)
            try:
                response = self.session.request(method=method, url=url, **kwargs)

                # Se atingiu o limite de requisições da Loja Integrada (429 ou 633)
                if response.status_code in (429, 633):
                    wait_time = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"Limite de requisições Loja Integrada atingido (Status {response.status_code}). "
                        f"Aguardando {wait_time:.1f}s antes de tentar novamente (Tentativa {attempt}/{max_retries})..."
                    )
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response

            except requests.RequestException as e:
                if attempt == max_retries:
                    logger.error(f"Erro permanente na chamada {method} {url}: {e}")
                    raise
                wait_time = base_delay * (2 ** (attempt - 1))
                logger.warning(f"Erro de rede na chamada {method} {url}: {e}. Retentando em {wait_time:.1f}s...")
                time.sleep(wait_time)

        raise RuntimeError(f"Falha ao executar requisição após {max_retries} tentativas: {url}")

    def list_products(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Lista produtos da loja com paginação."""
        params = {"limit": limit, "offset": offset}
        res = self._request_with_retry("GET", "/produto/", params=params)
        return res.json()

    def get_product(self, product_id: int | str) -> Dict[str, Any]:
        """Obtém todos os detalhes de um produto específico."""
        res = self._request_with_retry("GET", f"/produto/{product_id}/")
        return res.json()

    def get_seo_detail(self, seo_uri_or_id: int | str) -> Optional[Dict[str, Any]]:
        """
        Busca os dados de SEO na API (/v1/seo/{id}).
        Aceita tanto o ID numérico quanto a URI (ex: '/api/v1/seo/139836216').
        """
        if not seo_uri_or_id:
            return None

        seo_id = str(seo_uri_or_id).strip("/").split("/")[-1]
        if not seo_id.isdigit():
            return None

        try:
            res = self._request_with_retry("GET", f"/seo/{seo_id}")
            return res.json()
        except Exception as e:
            logger.warning(f"Não foi possível buscar SEO ID {seo_id}: {e}")
            return None

    def update_product_description(self, product_id: int | str, html_description: str) -> Dict[str, Any]:
        """Atualiza apenas a descrição completa HTML do produto."""
        payload = {"descricao_completa": html_description}
        res = self._request_with_retry("PUT", f"/produto/{product_id}/", json=payload)
        return res.json()

    def update_or_create_seo(
        self,
        product_id: int | str,
        seo_id: Optional[int | str],
        title: str,
        description: str,
        keyword: str = "",
    ) -> Dict[str, Any]:
        """
        Atualiza o SEO existente via PUT /v1/seo/{id} ou cria novo via POST /v1/seo/.
        """
        payload = {
            "title": title.strip(),
            "description": description.strip(),
        }
        if keyword:
            payload["keyword"] = keyword.strip()

        if seo_id:
            # Já possui registro de SEO na Loja Integrada -> PUT
            res = self._request_with_retry("PUT", f"/seo/{seo_id}", json=payload)
            return res.json()
        else:
            # Não possui registro de SEO -> POST associando ao produto
            payload["base_uri"] = f"/api/v1/produto/{product_id}"
            res = self._request_with_retry("POST", "/seo/", json=payload)
            return res.json()

    def sync_catalog_to_sqlite(
        self,
        max_products: int = 50,
        only_active: bool = True,
        only_available: bool = True,
        only_missing_seo: bool = False,
        stop_event: Optional[Any] = None,
        progress_callback: Optional[Any] = None,
    ) -> int:
        """
        Varre o catálogo da Loja Integrada e sincroniza com o banco local SQLite.
        Se only_available=True, descarta produtos desativados, bloqueados, removidos ou sem estoque.
        """
        offset = 0
        page_size = 50
        saved_count = 0
        scanned_count = 0

        logger.info(f"Iniciando sincronização (Apenas Disponíveis: {only_available})...")

        while True:
            if stop_event and stop_event.is_set():
                logger.info("Sincronização interrompida pelo usuário.")
                break

            data = self.list_products(limit=page_size, offset=offset)
            objects = data.get("objects", [])
            total_count = data.get("meta", {}).get("total_count", 0)

            if not objects:
                break

            target_total = min(max_products, total_count) if max_products > 0 else total_count

            for summary_prod in objects:
                if stop_event and stop_event.is_set():
                    break

                scanned_count += 1
                prod_id = summary_prod.get("id")

                try:
                    full_prod = self.get_product(prod_id)
                except Exception as err:
                    logger.warning(f"Erro ao obter produto {prod_id}: {err}")
                    continue

                # Validação rigorosa de disponibilidade se solicitado
                if only_available:
                    if full_prod.get("removido", False) or full_prod.get("bloqueado", False):
                        continue
                    if not full_prod.get("ativo", False):
                        continue
                    if full_prod.get("estoque_gerenciado", False):
                        qty = full_prod.get("estoque_quantidade")
                        if qty is None or float(qty) <= 0:
                            continue
                elif only_active and not full_prod.get("ativo", True):
                    continue

                # Busca dados de SEO
                seo_uri = full_prod.get("seo")
                seo_data = None
                if seo_uri and isinstance(seo_uri, str):
                    seo_data = self.get_seo_detail(seo_uri)

                # Filtro missing_seo
                has_seo = bool(seo_data and seo_data.get("title") and seo_data.get("description"))
                if only_missing_seo and has_seo:
                    continue

                # Salva no SQLite
                upsert_product_from_li(full_prod, seo_data)
                saved_count += 1

                msg = f"Sincronizados: {saved_count} produtos (Analisados {scanned_count}/{total_count})..."
                logger.info(f"#{prod_id} - '{full_prod.get('nome')}' (Estoque: {full_prod.get('estoque_quantidade')})")

                if progress_callback:
                    progress_callback(saved_count, target_total, msg)

                if max_products > 0 and saved_count >= max_products:
                    logger.info(f"Limite estipulado de {max_products} produtos alcançado.")
                    return saved_count

            offset += len(objects)
            if offset >= total_count:
                break

        logger.info(f"Sincronização concluída. Total salvo: {saved_count}")
        return saved_count

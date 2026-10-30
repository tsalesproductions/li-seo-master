import json
import logging
import re
from typing import Dict, Any, Optional
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL
from db import get_setting

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GPTGenerator")

SYSTEM_PROMPT = """Você é o principal especialista em E-commerce, Copywriting de Alta Conversão e SEO On-Page no Brasil.
Sua missão é transformar informações de produtos em uma página de vendas completa, persuasiva e com SEO perfeito para o Google.

ESTRUTURA OBRIGATÓRIA DA DESCRIÇÃO (HTML):
Você deve seguir o padrão institucional da loja:

<h2>DESCRIÇÃO</h2>
<div class="texto-descr-produto">
    <p>[Texto envolvente, persuasivo, destacando a proposta de valor, a sensação de ter o produto, seus diferenciais e a experiência de uso. Escreva parágrafos fluidos, ricos e completos, sem economizar qualidade ou profundidade.]</p>
    <p>[Segundo parágrafo aprofundando os detalhes, jogabilidade/utilidade prática, tecnologias, design e por que ele é indispensável.]</p>
</div>

[Se houver imagens ou estilos já presentes na descrição original, PRESERVE-OS intactos aqui!]

<h2>ESPECIFICAÇÕES</h2>
<ul>
    <li><strong>Fabricante:</strong> [Nome]</li>
    <li><strong>Modelo / Compatibilidade:</strong> [Detalhes]</li>
    <li><strong>Detalhes Técnicos:</strong> [Outras especificações relevantes]</li>
</ul>

<h2>ITENS INCLUSOS</h2>
<ul>
    <li>[Item 1]</li>
    <li>[Item 2]</li>
</ul>

<h2>GARANTIA</h2>
<ul>
    <li>3 meses contra defeitos de fabricação</li>
</ul>

<h2>TAGS</h2>
<ul class="keywords-tags">
    <li><a href="{store_url}/buscar?q=palavra+chave" style="text-decoration:none; color:inherit;">Palavra Chave</a></li>
    [Gere entre 6 e 12 tags relevantes de busca com links para {store_url}/buscar?q=termo_com_mais]
</ul>

DIRETRIZES DE SEO:
1. SEO TITLE:
   - Entre 50 e 60 caracteres.
   - Nome principal do produto + principal atrativo/diferencial + " | {store_name}".
   - Nunca passe de 65 caracteres.

2. SEO DESCRIPTION (Meta Description):
   - Entre 140 e 155 caracteres.
   - Texto persuasivo para o buscador do Google com verbo de ação e gatilho de compra (Ex: Garanta o seu com envio rápido, melhores condições e parcelamento sem juros!).

3. SEO KEYWORDS:
   - 5 a 8 palavras-chave mais buscadas separadas por vírgula.

Você DEVE responder EXCLUSIVAMENTE em formato JSON com as chaves:
{
  "seo_title": "...",
  "seo_description": "...",
  "seo_keywords": "...",
  "descricao_completa_html": "..."
}
"""


class GPTGenerator:
    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY não configurada no arquivo .env.")
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = OPENAI_MODEL

    def _extract_existing_media(self, html_text: str) -> str:
        """Extrai blocos de imagem e estilos presentes no HTML antigo para preservar na nova descrição."""
        if not html_text:
            return ""
        
        extracted = []
        # Procura tags de imagem
        imgs = re.findall(r"(<p[^>]*>\s*<img[^>]+>\s*</p>|<img[^>]+>)", html_text, re.IGNORECASE)
        for img in imgs:
            if img not in extracted:
                extracted.append(img)

        # Procura estilos embutidos
        styles = re.findall(r"(<style[^>]*>.*?</style>)", html_text, re.IGNORECASE | re.DOTALL)
        for style in styles:
            if style not in extracted:
                extracted.append(style)

        return "\n".join(extracted)

    def generate_seo_and_copy(self, product: Dict[str, Any]) -> Dict[str, str]:
        """
        Gera SEO + Descrição rica formatada a partir dos dados do produto.
        """
        store_name = get_setting("store_name", "ShopB")
        store_url = get_setting("store_url", "https://www.shopb.com.br").rstrip("/")

        prod_id = product.get("id")
        nome = product.get("nome", "Produto")
        sku = product.get("sku", "")
        preco = product.get("preco", "")
        descricao_atual = product.get("descricao_atual") or product.get("descricao_completa") or ""

        # Preserva mídias existentes
        midias_preservadas = self._extract_existing_media(descricao_atual)

        user_content = f"""
Crie a otimização completa (SEO + Descrição Rica) para este produto:

- ID do Produto: {prod_id}
- Nome do Produto: {nome}
- SKU: {sku}
- Preço: R$ {preco}
- Mídias/Imagens existentes para preservar (se houver):
{midias_preservadas if midias_preservadas else 'Nenhuma imagem cadastrada no HTML.'}

- Descrição Original Atual:
{descricao_atual[:3000] if descricao_atual else 'Produto sem descrição cadastrada. Desenvolva do zero com base no nome do produto.'}
"""

        system_content = (
            SYSTEM_PROMPT.replace("{store_name}", store_name)
            .replace("{store_url}", store_url)
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.7,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": system_content,
                    },
                    {"role": "user", "content": user_content},
                ],
            )
            raw_text = response.choices[0].message.content
            parsed = json.loads(raw_text)

            html_gerado = parsed.get("descricao_completa_html", "").strip()

            # Se havia mídias originais e o GPT não incluiu, nós re-injetamos para garantir que nunca se perca uma foto
            if midias_preservadas and "<img" not in html_gerado:
                # Insere logo após o fechamento da div texto-descr-produto
                if "</div>" in html_gerado:
                    html_gerado = html_gerado.replace("</div>", f"</div>\n\n{midias_preservadas}\n", 1)
                else:
                    html_gerado = f"{html_gerado}\n\n{midias_preservadas}"

            return {
                "seo_title": parsed.get("seo_title", "").strip(),
                "seo_description": parsed.get("seo_description", "").strip(),
                "seo_keywords": parsed.get("seo_keywords", "").strip(),
                "descricao_completa_html": html_gerado,
            }
        except Exception as e:
            logger.error(f"Erro ao gerar com GPT para o produto {prod_id} ({nome}): {e}")
            raise

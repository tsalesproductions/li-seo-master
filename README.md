# 🚀 LI SEO & Copy Master (Loja Integrada + OpenAI)

Projeto funcional e seguro para auditar, gerar e atualizar **Descrições de Alta Conversão** e **SEO On-Page (Title, Meta Description, Keywords)** para produtos da **Loja Integrada**, utilizando modelos de IA da OpenAI (`gpt-4o-mini` / `gpt-4o`).

Desenvolvido especialmente para e-commerces que já faturam e não podem correr riscos com alterações diretas sem validação e controle de falhas.

---

## 💡 Por que este fluxo é ideal para E-commerce?

1. **Sem Complexidade Desnecessária:** Não precisa de banco de dados, dashboard pesado ou autenticação OAuth complexa do Google Cloud.
2. **Revisão Humana Segura (Aprovação):** A IA gera tudo em uma planilha (`.xlsx` e `.csv`) que você pode abrir no **Excel** ou importar no **Google Sheets**. Você aprova, rejeita ou ajusta o texto antes de enviar para a loja virtual.
3. **Respeito aos Limites da Loja Integrada (Rate Limits):** A API da Loja Integrada limita as requisições em **100 req/min por loja**. O script possui controle automático de intervalo (`0.8s`) e retentativas com backoff exponencial contra erros `429` e `633`.
4. **Snapshot de Backup Automático + Rollback:** Antes de qualquer alteração ir para o ar, os dados originais exatos dos produtos são salvos em `backups/`. Se você quiser desfazer qualquer alteração, basta rodar um comando para restaurar o estado anterior.
5. **Prompt de Alta Conversão focado no Brasil:** Gera HTML semântico limpo para a descrição (benefícios, especificações, gatilhos de segurança) e SEO otimizado para o padrão da SERP do Google (título até 60 caracteres, descrição persuasiva até 155 caracteres).

---

## 📂 Estrutura do Projeto

```
li-seo-master/
├── .env.example          # Modelo de configuração com todas as variáveis
├── requirements.txt      # Dependências do projeto (requests, openai, flask, openpyxl, etc.)
├── config.py             # Validação e carregamento de variáveis de ambiente
├── db.py                 # Camada SQLite local (inicialização automática, consultas, paginação)
├── li_client.py          # Cliente HTTP da Loja Integrada (Auth, Rate Limiting, Retry)
├── gpt_generator.py      # Prompt especializado de Alta Conversão e integração com OpenAI
├── storage.py            # Planilhas de backup e relatórios de segurança
├── task_manager.py       # Gerenciador de tarefas em segundo plano (threads assíncronas)
├── app.py                # Servidor Web Flask (Dashboard interativo em http://localhost:5000)
├── templates/            # Frontend do Dashboard Web (Tailwind CSS, visualizador e editor)
└── main.py               # Interface CLI unificada (modos: web, scan, generate, publish)
```

---

## 🛠️ Passo a Passo para Configuração

### 1. Instalar Dependências

No terminal ou prompt de comando (com Python 3.10+):

```bash
pip install -r requirements.txt
```

### 2. Configurar o arquivo `.env`

Copie o `.env.example` para `.env`:

```bash
copy .env.example .env
```

Abra o arquivo `.env` e preencha suas chaves:

```ini
# Loja Integrada - Opção 1: Personal Token (Recomendado)
LI_PERSONAL_TOKEN=seu_personal_token_aqui

# Loja Integrada - Opção 2: Chaves Legadas (Caso não use personal token)
LI_CHAVE_API=
LI_CHAVE_APLICACAO=

# OpenAI
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini

# Regras de Negócio
STORE_NAME=Nome da Sua Loja
PRODUCT_LIMIT=20                    # Quantidade de produtos para processar por lote
ONLY_MISSING_SEO_OR_DESC=true       # Processar apenas produtos sem SEO ou sem descrição
ONLY_ACTIVE_PRODUCTS=true           # Apenas produtos ativos na loja
DRY_RUN=false                       # Se true, simula sem enviar para a LI
```

---

## 🚀 Como Usar no Dia a Dia

O projeto pode ser operado tanto pelo **Dashboard Web visual** (recomendado) quanto via **Terminal CLI**:

### Opção 1: Dashboard Web Visual (Recomendado)

Inicie o painel local:
```bash
python main.py --mode web
# ou: python app.py
```
Acesse no navegador: **`http://localhost:5000`**

No Dashboard você pode:
* Sincronizar catálogo da Loja Integrada em segundo plano sem travar a interface.
* Filtrar por **Status de IA** (*Gerados* ou *Não gerados*), **SEO na Loja** (*Sem SEO* ou *Com SEO*) e **Status de Aprovação** (*Pendentes*, *Aprovados*, *Publicados*).
* Navegar por paginação completa de todos os produtos do catálogo.
* Abrir o modal para revisar lado a lado as meta tags e o preview visual do HTML gerado.
* Gerar em lote ou publicar aprovados diretamente na loja com 1 clique.

---

### Opção 2: Linha de Comando (CLI)

#### Passo 1: Diagnóstico e Sincronização
Varre o catálogo da loja e sincroniza com o banco local SQLite:
```bash
python main.py --mode scan
```

#### Passo 2: Gerar Sugestões com IA
Gera SEO e Copywriting para os produtos pendentes que ainda não possuem IA:
```bash
# Processa o lote padrão (definido no .env)
python main.py --mode generate

# Ou defina a quantidade desejada:
python main.py --mode generate --limit 50

# Ou processe todos os produtos pendentes:
python main.py --mode generate --all
```

#### Passo 3: Publicar na Loja Integrada
Atualiza os produtos aprovados na API da Loja Integrada (com criação automática de snapshot de segurança):
```bash
python main.py --mode publish
```
> **Nota de Segurança:** Se quiser testar antes sem aplicar alterações reais na loja, ative `DRY_RUN=true` no arquivo `.env`.

---

## 🛡️ Como Desfazer Alterações (Rollback)

Se por qualquer motivo você precisar voltar os produtos para o estado original em que estavam antes do script rodar:

```bash
python main.py --mode rollback --backup backups/backup_antes_do_update_YYYYMMDD_HHMMSS.json
```
O script lê o arquivo de backup e restaura o SEO e descrição antigos via API na Loja Integrada.

---

## ⚡ Limites de Requisições e Autenticação da Loja Integrada

- **Autenticação:** O script suporta nativamente o **Personal Token** (gerado no painel da LI em *Aplicativos > Personal Token*) e o esquema tradicional de chaves (`chave_api` e `chave_aplicacao`).
- **Rate Limit:** A Loja Integrada possui um limite de **100 requisições por minuto por loja**. O `li_client.py` inclui um espaçamento suave configurável (`LI_REQUEST_DELAY=0.8s`) e captura automaticamente os códigos de erro de sobrecarga (`429` e `633`), pausando a execução com espera exponencial antes de tentar novamente, garantindo que sua loja virtual nunca seja prejudicada.


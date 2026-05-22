# DenialFlow AI (EVA) — Documentação completa dos fluxos

**Versão:** POC · **Data:** maio/2026  
**Escopo:** FastAPI, CrewAI, AWS Bedrock, RAG (Chroma + OpenAI), Streamlit, Gmail, AgentOps, SQLite.

---

## Sumário executivo

O **DenialFlow AI** é uma plataforma de demonstração para resolução de **negativas de saúde** (RCM). O fluxo operacional é:

1. **Ingestão** — upload de CSV com claims negadas → SQLite (`pending`).
2. **Automação** — workflow em background: classificação → priorização → RAG → carta de recurso (CrewAI) → `awaiting_review`.
3. **Conhecimento** — corpus vetorial em Chroma (`denialflow_corpus`), alimentado por `seed_vectorstore.py`.
4. **Revisão humana (HITL)** — Streamlit: segunda opinião opcional (Bedrock), approve / edit / reject.
5. **Notificação** — Gmail API em approve/edit (opcional).
6. **Visibilidade** — dashboard de métricas, eventos de workflow, AgentOps (opcional).

> Dados sintéticos apenas. Não processar PHI em produção sem controles de compliance.

---

## 1. Visão geral da arquitetura

```mermaid
flowchart TB
  subgraph client [Cliente]
    ST[Streamlit multipage]
    HTTP[Cliente HTTP / api.http]
  end

  subgraph api [FastAPI denialflow_ai/api]
    Auth[JWT / Bearer static]
    RClaims[claims router]
    RWF[workflows router]
    RAppeals[appeals router]
    RMetrics[metrics router]
    Health["/health publico"]
  end

  subgraph services [Servicos]
    CSV[csv_ingest]
    WFS[workflow_service]
    Letter[appeal_letter_context]
    Gmail[gmail_notify]
  end

  subgraph ai [IA]
    C1[classification crew]
    C2[prioritization crew]
    RAGasync[retrieve_for_claim async]
    C3[appeal crew + PolicyAppealSearchTool]
    C4[appeal_review Bedrock/Groq]
  end

  subgraph storage [Persistencia]
    SQLite[(SQLite denialflow.db)]
    Chroma[(Chroma data/chroma)]
  end

  subgraph external [Externos]
    Groq[Groq / OpenAI LLM]
    OpenAI[OpenAI embeddings]
    Bedrock[AWS Bedrock]
    AgentOps[AgentOps tracing]
    GmailAPI[Gmail API]
  end

  ST -->|Bearer token| api
  HTTP --> api
  RClaims --> CSV --> SQLite
  RWF --> WFS
  WFS --> C1 --> C2 --> RAGasync --> C3
  C3 --> Chroma
  RAGasync --> Chroma
  WFS --> SQLite
  RAppeals --> C4
  RAppeals --> Gmail
  C1 & C2 & C3 & C4 --> Groq
  RAGasync --> OpenAI
  C4 --> Bedrock
  WFS --> AgentOps
```

### Pontos de entrada

| Componente | Comando | Papel |
|------------|---------|-------|
| API | `uvicorn denialflow_ai.api.app:app` | `create_app()` em `denialflow_ai/api/app.py` |
| UI | `streamlit run streamlit_app/Home.py` | Cliente REST desacoplado |
| Seed RAG | `python scripts/seed_vectorstore.py` | Popula Chroma com `data/seed_documents/*.md` |
| Token JWT | `python scripts/generate_api_token.py` | Gera `API_ACCESS_TOKEN` para `.env` |

### Stack tecnológica

| Camada | Tecnologia | Uso |
|--------|------------|-----|
| API HTTP | **FastAPI** + Uvicorn | Rotas REST `/v1/*`, background tasks, lifespan |
| Agentes | **CrewAI** | Crews sequenciais: classificação, priorização, apelação |
| LLM workflow | **Groq** ou **OpenAI** (`LLM_PROVIDER`) | Classificação, priorização, carta via `llm_config.py` |
| LLM 2ª opinião | **AWS Bedrock** (Claude via LiteLLM) | `POST /v1/appeals/{id}/ai-review` |
| Embeddings | **OpenAI** `text-embedding-3-small` | RAG async + sync |
| Vetor | **ChromaDB** persistente | Coleção `denialflow_corpus` em `data/chroma/` |
| DB relacional | **SQLite** + aiosqlite | Claims, batches, appeals, audit, workflow_runs |
| UI | **Streamlit** | 5 páginas + Home |
| E-mail | **Gmail API** (OAuth ou service account) | Após approve/edit |
| Observabilidade | **AgentOps** + structlog | Traces por workflow e ai-review |
| Auth | **JWT** + token estático | Bearer em todas as rotas `/v1/*` |

---

## 2. Inicialização da API (lifespan FastAPI)

Ao subir o Uvicorn, o `lifespan` de `create_app()` executa:

```mermaid
sequenceDiagram
  participant Uvicorn
  participant App as create_app
  participant Life as lifespan
  participant DB as init_database
  participant AO as AgentOps
  participant Emb as embeddings check

  Uvicorn->>App: startup
  App->>Life: enter lifespan
  Life->>Life: configure_logging
  Life->>Life: validate_auth_config
  alt AGENTOPS_API_KEY set
    Life->>AO: agentops.init
  end
  Life->>DB: init_db SQLite + migrations
  alt LLM_PROVIDER=groq
    Life->>Emb: require OPENAI_API_KEY
  end
  Life-->>Uvicorn: ready
  Note over Uvicorn: serve /v1/* + /health
  Uvicorn->>Life: shutdown
  Life->>AO: end_session
```

**Middleware em cada request:** `RequestContextMiddleware` (request_id, trace_id, latência) + CORS permissivo (`*`).

**Arquivos:** `denialflow_ai/api/app.py`, `denialflow_ai/core/logging.py`, `denialflow_ai/observability/middleware.py`.

---

## 3. Autenticação (rotas `/v1/*`)

```mermaid
flowchart TD
  Req[Request com Authorization Bearer]
  Enabled{JWT_AUTH_ENABLED?}
  Anon[Principal sub=anonymous]
  Missing{Header presente?}
  Static{Token == API_ACCESS_TOKEN?}
  JWT{3 segmentos + JWT_SECRET?}
  OK[Principal valido]
  E401[401 Unauthorized]

  Req --> Enabled
  Enabled -->|false| Anon
  Enabled -->|true| Missing
  Missing -->|nao| E401
  Missing -->|sim| Static
  Static -->|match| OK
  Static -->|nao| JWT
  JWT -->|decode ok| OK
  JWT -->|falha| E401
```

- **Público:** apenas `GET /health`
- **Protegido:** routers com `Depends(get_current_principal)`
- **HITL:** `approve` / `reject` / `edit` gravam `principal["sub"]` no `audit_log`
- **Implementação:** `denialflow_ai/api/auth.py`, `denialflow_ai/api/deps.py`

---

## 4. Fluxo operacional end-to-end (POC)

```mermaid
flowchart TD
  A[Gerar CSV + seed Chroma] --> B[Upload CSV]
  B --> C[Criar batch + claims pending]
  C --> D[POST workflows/run]
  D --> E[Background execute_workflow_run]
  E --> F[Por claim: classificar priorizar RAG apelar]
  F --> G[Status awaiting_review]
  G --> H[Streamlit Appeal Review]
  H --> I{Decisao humana}
  I -->|opcional| J[POST ai-review Bedrock]
  I -->|approve| K[approved + email]
  I -->|edit| L[edited + email]
  I -->|reject| M[rejected sem email]
  K & L & M --> N[Dashboard metricas atualizadas]
```

### Estados do claim (SQLite)

`pending` → `classified` → `prioritized` → `retrieved` → `awaiting_review` → `approved` | `rejected` | `edited`

---

## 5. Upload de CSV

```mermaid
sequenceDiagram
  participant UI as Streamlit Upload
  participant API as POST /v1/claims/upload
  participant Parse as csv_ingest
  participant Batch as BatchRepository
  participant Claims as ClaimRepository

  UI->>API: multipart CSV file
  API->>Parse: parse_claims_csv
  Parse-->>API: rows + errors
  alt claim_id duplicado no batch
    API-->>UI: 409 Conflict
  else ok
    API->>Batch: create batch_id
    API->>Claims: insert_many status=pending
    API-->>UI: batch_id, accepted_count
    UI->>UI: session last_batch_id
  end
```

**Colunas obrigatórias:** `claim_id`.  
**Clínico/financeiro:** `payer`, `denial_code`, valores, CPT/ICD, etc.  
**Letterhead (opcional):** `provider_name`, endereços, `signer_name` — evita placeholders `[Your Company Name]` na carta.

**Arquivos:** `denialflow_ai/api/routers/claims.py`, `streamlit_app/pages/2_Upload.py`.

---

## 6. Workflow — núcleo do sistema

### 6.1 Disparo e monitoramento

```mermaid
sequenceDiagram
  participant UI as Upload ou API
  participant API as POST /v1/workflows/run
  participant BG as BackgroundTasks
  participant WFS as execute_workflow_run
  participant WF as WorkflowRepository

  UI->>API: batch_id, max_claims
  API->>WF: create_run status=running
  API->>BG: enqueue execute_workflow_run
  API-->>UI: run_id, running
  BG->>WFS: processar batch
  loop cada claim pending
    WFS->>WF: add_event por fase
  end
  WFS->>WF: complete_run completed ou failed
```

**Monitoramento:** `streamlit_app/pages/3_Workflow.py` — polling `GET /v1/workflows/{id}`, eventos, auto-refresh 5s.

### 6.2 Pipeline por claim (detalhado)

```mermaid
flowchart TD
  Start[Claim status=pending] --> E1[event classification]
  E1 --> Crew1[run_denial_classification]
  Crew1 --> Save1[save_classification]
  Save1 --> S1[status classified]

  S1 --> E2[event prioritization]
  E2 --> Crew2[run_financial_prioritization]
  Crew2 --> Save2[save_prioritization]
  Save2 --> S2[status prioritized]

  S2 --> E3[event rag]
  E3 --> RAG[retrieve_for_claim async OpenAI embed]
  RAG --> Save3[save_rag + citations]
  Save3 --> S3[status retrieved]

  S3 --> E4[event appeal]
  E4 --> Letter[build_letter_context do CSV]
  Letter --> Crew3[run_research_and_appeal]
  Crew3 --> Sanitize[sanitize_appeal_body]
  Sanitize --> Draft[AppealRepository.create_draft]
  Draft --> S4[status awaiting_review]
  S4 --> E5[event hitl]

  Budget{budget_used maior que WORKFLOW_TOKEN_BUDGET?}
  Crew1 --> Budget
  Crew2 --> Budget
  Crew3 --> Budget
  Budget -->|sim| Stop[para batch cedo warning]
  Budget -->|nao| S4
```

**Implementação central:** `denialflow_ai/services/workflow_service.py`.

**Orçamento de tokens:** estimativa grosseira (`len(text)//4`); ao exceder `WORKFLOW_TOKEN_BUDGET`, o batch para cedo com warning no log de eventos.

---

## 7. Crews CrewAI (agentes)

### 7.1 Classificação de negativa

| Item | Detalhe |
|------|---------|
| Arquivo | `denialflow_ai/crews/classification.py` |
| Entrada | JSON do claim (`_claim_text`) |
| Saída | `category`, `confidence`, `explanation` |
| Categorias | `coding_issue`, `authorization`, `duplicate_claim`, `medical_necessity`, `incomplete_documentation` |
| Sequência | 1 agente → 1 task → JSON |
| Cache | TTL em memória por hash do payload |
| Fallback | `chat_json` direto se o crew falhar |

### 7.2 Priorização financeira

| Item | Detalhe |
|------|---------|
| Arquivo | `denialflow_ai/crews/prioritization.py` |
| Entrada | claim JSON + resumo da classificação |
| Saída | `priority_score`, `estimated_recoverable_revenue`, `urgency`, `reversal_probability`, `recommended_action` |
| Sequência | 1 agente → 1 task com `output_pydantic` |

### 7.3 Pesquisa + carta de recurso (Crew C)

```mermaid
flowchart LR
  subgraph appealCrew [Appeal Crew sequencial]
    A1[Agente Researcher]
    T1[Task pesquisa interna]
    Tool[PolicyAppealSearchTool]
    A2[Agente Writer]
    T2[Task carta ao payer]
  end

  Input[claim + cls + pri + letter_context] --> A1
  A1 --> T1 --> Tool
  Tool --> ChromaSync[retrieve_sync Chroma]
  T1 --> A2
  A2 --> T2
  T2 --> Out[appeal_markdown + CONFIDENCE line]
```

- **Tool RAG:** `denialflow_ai/tools/rag_tool.py` — busca síncrona no corpus
- **Regras:** sem placeholders `[...]`; `doc_id` só em notas internas
- **Citações no DB:** do RAG **async** do workflow (passo 3), não necessariamente dos hits da tool
- **Fallback:** `appeal_text()` via LLM sem tool

### 7.4 Segunda opinião — AWS Bedrock (fora do workflow)

```mermaid
flowchart TD
  Human[Revisor clica Gerar analise] --> API[POST /v1/appeals/id/ai-review]
  API --> Crew4[run_appeal_second_opinion]
  Crew4 --> Docs{Citacoes no appeal?}
  Docs -->|vazias ou BEDROCK_REVIEW_RAG_REFRESH| Refresh[retrieve_sync draft]
  Docs -->|default| Stored[citations_json do workflow]
  Crew4 --> Path{config}
  Path -->|BEDROCK_REVIEW_FALLBACK_GROQ| Groq[Groq only]
  Path -->|BEDROCK_REVIEW_USE_CREWAI| CrewAI[CrewAI + Bedrock]
  Path -->|default| Bedrock[LiteLLM Bedrock throttle fallback Groq]
  Crew4 --> Save[save_ai_review + audit]
  Save --> UI[Exibe 2a opiniao na UI]
```

**Importante:** a 2ª opinião **não altera** o status do claim automaticamente. O workflow principal continua em Groq/OpenAI; Bedrock é só em `ai-review`.

**Variáveis `.env` relevantes:**

- `AWS_REGION`, `BEDROCK_MODEL_REVIEW`, `BEDROCK_REVIEW_ENABLED`
- `BEDROCK_REVIEW_USE_CREWAI` — usar CrewAI com LLM Bedrock vs LiteLLM direto
- `BEDROCK_REVIEW_FALLBACK_GROQ` — quota Bedrock excedida → Groq
- `BEDROCK_REVIEW_RAG_REFRESH` — re-buscar Chroma com texto do draft

**Arquivo:** `denialflow_ai/crews/appeal_review.py`  
**UI:** `streamlit_app/pages/5_Appeal_Review.py`

### 7.5 LLM compartilhado (`llm_config.py`)

- `LLM_PROVIDER`: `groq` ou `openai`
- Cadeia de fallback de modelos Groq
- `kickoff_crew_with_model_fallback` + contexto AgentOps por kickoff
- Bedrock via LiteLLM para review (`build_llm_bedrock`, `ensure_bedrock_env`)

---

## 8. Fluxo RAG (duas vias)

```mermaid
flowchart TB
  Seed[scripts/seed_vectorstore.py] --> Chunk[chunk MD files]
  Chunk --> EmbedOAI[OpenAI text-embedding-3-small]
  EmbedOAI --> Chroma[(Chroma denialflow_corpus)]

  subgraph pipeline [Workflow async]
    W1[retrieve_for_claim] --> EmbedAsync[embed_texts async]
    EmbedAsync --> Query1[query Chroma]
    Query1 --> SaveDB[rag_retrievals + citations_json no appeal]
  end

  subgraph sync [Tool + Bedrock review]
    W2[retrieve_sync] --> EmbedSync[embed_texts_sync]
    EmbedSync --> Query2[query Chroma]
  end

  Chroma --> W1
  Chroma --> W2
```

| Via | Função | Quando |
|-----|--------|--------|
| **Async** | `retrieve_for_claim` | Passo 3 do workflow; persiste citações no appeal |
| **Sync** | `retrieve_sync` | `PolicyAppealSearchTool` no Crew C; refresh Bedrock review |

Diretório: `data/chroma/` · documentos: `data/seed_documents/*.md`.

---

## 9. HITL — revisão humana de appeals

```mermaid
flowchart TD
  List[GET /v1/appeals status=awaiting_review] --> Select[Selecionar appeal_id]
  Select --> Detail[GET /v1/appeals/id]
  Detail --> View[Draft + RAG citations + cls/pri JSON]

  View --> Opt{2a opiniao?}
  Opt -->|sim| AI[POST ai-review timeout 120s]
  AI --> View2[AppealAIReview score issues acao sugerida]

  View2 --> Decision{Decisao humana}
  View --> Decision

  Decision -->|approve| Approve[POST approve]
  Decision -->|reject| Reject[POST reject + reason]
  Decision -->|edit| Edit[POST edit final_text + reason]

  Approve --> StA[claim approved + audit]
  Edit --> StE[claim edited + audit]
  Reject --> StR[claim rejected + audit]

  Approve --> Email{GMAIL_NOTIFY_ENABLED?}
  Edit --> Email
  Email -->|sim| Send[send_appeal_decision_email]
  Email -->|nao| Skip[audit email_skipped]
  Reject --> NoMail[sem email]
```

**Gmail** (`denialflow_ai/services/gmail_notify.py`): OAuth (`gcp/key_gmail.json` + `gmail_token.json`) ou service account Workspace. Falha de e-mail **não reverte** a decisão salva (exceto `GMAIL_FAIL_ON_ERROR=true` → HTTP 502).

**Sanitização da carta:** `denialflow_ai/services/appeal_letter_context.py`.

---

## 10. Jornada Streamlit (UI)

```mermaid
flowchart LR
  Home[Home health check]
  P1[1 Dashboard metricas]
  P2[2 Upload ingest + start run]
  P3[3 Workflow monitor run_id]
  P4[4 Claims Analysis triagem]
  P5[5 Appeal Review HITL]

  Home --> P1
  Home --> P2
  P2 -->|last_run_id session| P3
  P2 -->|pipeline gera appeals| P5
  P3 --> P4
  P1 --> P4
  P4 --> P5
```

| Página | Ações | API |
|--------|-------|-----|
| `Home.py` | URL da API, saúde | `GET /health` (sem auth) |
| `1_Dashboard.py` | KPIs | `GET /v1/metrics/dashboard`, `/ops` |
| `2_Upload.py` | CSV + workflow | `POST /v1/claims/upload`, `POST /v1/workflows/run` |
| `3_Workflow.py` | Run ID, auto-refresh | `GET /v1/workflows/*` |
| `4_Claims_Analysis.py` | Filtro status | `GET /v1/claims/summary` |
| `5_Appeal_Review.py` | Bedrock + HITL | `GET/POST /v1/appeals/*` |

Cliente: `streamlit_app/api_client.py` — Bearer `API_ACCESS_TOKEN` do `.env`.

---

## 11. Métricas e observabilidade

### Dashboard (`GET /v1/metrics/dashboard`)

Agrega SQLite: total claims, proxy taxa negação, receita recuperável, fila `awaiting_review`, duração média de runs, top 10 prioridade.

### Ops in-memory (`GET /v1/metrics/ops`)

Latências e contadores do middleware (não persiste em DB).

### AgentOps

```mermaid
flowchart LR
  Life[lifespan init] --> AO[agentops.init]
  WFS[workflow phases] --> Bind[bind_workflow_context]
  Crew[kickoff_crew] --> Kick[crew_kickoff_context]
  Review[ai-review] --> BR[bedrock_review_context]
```

Módulo: `denialflow_ai/observability/agentops_client.py`.

---

## 12. Modelo de dados (SQLite)

```mermaid
erDiagram
  batches ||--o{ claims : contains
  claims ||--o{ classification_results : has
  claims ||--o{ prioritization_results : has
  claims ||--o{ rag_retrievals : has
  claims ||--o| appeals : has
  batches ||--o{ workflow_runs : triggers
  workflow_runs ||--o{ workflow_events : logs
  appeals ||--o{ audit_log : audited
  claims ||--o{ audit_log : audited
```

Repositórios: `denialflow_ai/repositories/` · schema: `denialflow_ai/db/`. **Chroma é separado** do SQLite.

---

## 13. Mapa da API REST

| Método | Caminho | Função |
|--------|---------|--------|
| GET | `/health` | Liveness (público) |
| POST | `/v1/claims/upload` | Ingestão CSV |
| GET | `/v1/claims` | Lista com filtro `status` |
| GET | `/v1/claims/summary` | Join claim + análises + appeal |
| POST | `/v1/workflows/run` | Inicia run em background |
| GET | `/v1/workflows` | Runs recentes |
| GET | `/v1/workflows/{run_id}` | Status do run |
| GET | `/v1/workflows/{run_id}/events` | Log de eventos |
| GET | `/v1/appeals` | Fila de revisão |
| GET | `/v1/appeals/{id}` | Detalhe completo |
| POST | `/v1/appeals/{id}/ai-review` | 2ª opinião Bedrock/Groq |
| POST | `/v1/appeals/{id}/approve` | Aprova + e-mail opcional |
| POST | `/v1/appeals/{id}/reject` | Rejeita |
| POST | `/v1/appeals/{id}/edit` | Edita texto final |
| GET | `/v1/metrics/dashboard` | KPIs |
| GET | `/v1/metrics/ops` | Métricas in-memory |

---

## 14. Scripts auxiliares

| Script | Fluxo |
|--------|-------|
| `generate_sample_csv.py` | CSV demo com letterhead |
| `seed_vectorstore.py` | Embeddings → Chroma |
| `generate_api_token.py` | JWT → `.env` |
| `gmail_authorize.py` | OAuth one-time Gmail |
| `generate_fluxos_pdf.py` | Gera este documento em PDF |

---

## 15. Integração AWS Bedrock (detalhe)

```mermaid
sequenceDiagram
  participant UI as Appeal Review
  participant API as appeals router
  participant Rev as appeal_review
  participant RAG as retrieve_sync
  participant BR as LiteLLM Bedrock
  participant GQ as Groq fallback

  UI->>API: POST ai-review
  API->>Rev: run_appeal_second_opinion
  Rev->>Rev: carrega draft_text + citations
  alt BEDROCK_REVIEW_RAG_REFRESH ou sem citacoes
    Rev->>RAG: query Chroma com draft
  end
  Rev->>BR: prompt JSON estruturado
  alt quota / throttle
    BR-->>Rev: erro rate limit
    Rev->>GQ: BEDROCK_REVIEW_FALLBACK_GROQ
  end
  Rev->>API: AppealAIReview persistido
  API-->>UI: score, issues, recommended_action
```

**Credenciais:** perfil AWS padrão ou variáveis de ambiente (`AWS_ACCESS_KEY_ID`, etc.). Modelo habilitado no console Bedrock da região configurada.

---

*Documento gerado para o repositório DenialFlow AI (EVA). Para atualizar o PDF: `python scripts/generate_fluxos_pdf.py`.*

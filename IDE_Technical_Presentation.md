# Intelligent Document Engine (IDE) — Technical Presentation

> **Status:** Live demo deployed on AWS (CloudFront + API Gateway + Lambda + S3 + Textract + Bedrock + DynamoDB).  
> **Domain:** `ide-doc.gitsoft.uk`

This document explains **what** we built, **how** it works end‑to‑end, and **why** we made key design choices. It is aimed at an AWS‑savvy audience and mirrors the eight major steps we followed.

---

## 0) High‑Level Goals

- Upload PDFs/images → extract text with **Textract** → chunk → **embed** with Bedrock **amazon.titan-embed-text-v2:0** → store vectors in **DynamoDB**.
- Answer user questions via semantic retrieval and light extractive synthesis; optionally polish the answer with **amazon.titan-text-express-v1**.
- Serve a secure static UI via **CloudFront** + private **S3**, route `/answer | /search | /upload` to **API Gateway** → **Lambda**.
- Keep costs/demo friction low, and security tight (no public buckets, OAC, authorizer header, presigned uploads, type allow‑list).

---

## 1) Edge, Domain & Static UI

**Components**
- **Route 53** — `ide-doc.gitsoft.uk` A/AAAA alias → **CloudFront**.
- **ACM (us-east-1)** — public TLS certificate for the subdomain.
- **CloudFront** — two origins & behaviors:
  - **Origin #1 (S3 UI)** — private bucket + **OAC**. **Default behavior** serves UI (HTML/CSS/JS).
  - **Origin #2 (API Gateway)** — behavior routes `POST/OPTIONS` for `/answer`, `/search`, `/upload` to the API.
- **S3 (UI bucket)** — private (no public ACLs).

**UI details**
- Single page (`index.html`, `style.css`, `app.js`) with **busy overlay**, **Top‑K slider**, same‑origin API by default, and `?api=` override (reveals an API field for testing).  
- Upload is direct‑to‑S3 via a presigned `PUT` URL returned by `/upload`.

**Why this setup**
- No public S3; OAC hardens access.
- API hostname isn’t exposed by default; behavioral routing keeps things tidy.
- Easy to cache static UI while leaving API uncached and protected.

---

## 2) Controlled Uploads (Signed URLs)

**Endpoint:** `POST /upload` → Lambda **`ide-upload-url`**  
**Purpose:** Issue short‑lived presigned `PUT` URL under `uploads/…` and enforce allowed content types.

**Key env vars**
- `BUCKET`, `DEFAULT_PREFIX=uploads/`, `EXPIRES_IN`
- `ALLOWED_TYPES=application/pdf,image/png,image/jpeg`

**Response**
```json
{
  "uploadUrl": "<signed PUT>",
  "key": "uploads/<ts>-<id>-<filename>.pdf",
  "s3Uri": "s3://<bucket>/uploads/...",
  "contentType": "application/pdf",
  "expiresIn": 900
}
```

**UI flow**
1) Call `/upload`.  
2) `PUT` the file directly to S3 using `uploadUrl`.  
3) Show status “Uploaded OK — processing…”.

---

## 3) Ingest Trigger (S3 → Textract Start)

**Trigger:** S3 `ObjectCreated` (prefix `uploads/`) → Lambda **`ide-textract-start`**  
**Purpose:** Start **asynchronous Textract** job, notify via **SNS**.

**Notes**
- Validates suffix/content type; optional head check for logging.
- Uses Textract async API (Text Detection); sets SNS topic for completion events.

---

## 4) Textract Completion Fan‑in (SNS → SQS → Lambda)

**Wiring:** SNS (Textract job events) → SQS `ide-textract-events` → Lambda **`ide-textract-callback`**  
**Purpose:** On completion, fetch all pages, normalize, write JSON to `s3://<bucket>/extracted/...json`.

**Output JSON (compact)**
```json
{
  "source_bucket": "...",
  "source_key": "uploads/.../file.pdf",
  "job_id": "…",
  "pages": [
    {"page": 1, "lines": ["...", "..."]},
    {"page": 2, "lines": ["...", "..."]}
  ]
}
```

---

## 5) Embedding + Indexing (S3 Extracted → Lambda → DynamoDB)

**Trigger:** S3 `ObjectCreated` (prefix `extracted/`, suffix `.json`) → Lambda **`ide-embed-index`**  
**Purpose:** Convert Textract JSON to chunks, embed with Bedrock Titan, index in DynamoDB.

**Key env vars**
- `TABLE_NAME=ide-rag`
- `BEDROCK_REGION`
- `BEDROCK_MODEL_ID=amazon.titan-embed-text-v2:0`
- `MAX_CHARS_PER_CHUNK=800`

**Process**
- Create stable `docId` from original file name (sans suffix).
- Chunk contiguous lines to ~≤800 chars (page‑aware); call Bedrock **Titan Embed**.
- Write items to DynamoDB (`docId`, `chunkId` like `PPPP#CCCCCC`, `page`, `text`, `source`, `vec`).

---

## 6) Search API (Semantic Retrieve Only)

**Endpoint:** `POST /search` → Lambda **`ide-query`**  
**Purpose:** Embed query → cosine against all chunks in DynamoDB → return Top‑K.

**Key env vars**
- `TABLE_NAME`, `BEDROCK_REGION`, `BEDROCK_MODEL_ID=amazon.titan-embed-text-v2:0`

**Response**
```json
{
  "top_k": [
    {"score":0.87,"docId":"…","chunkId":"0005#000003","page":5,"text":"…","source":"s3://…"}
  ]
}
```

**Notes**
- Uses full table scan (adequate at demo scale) + cosine in Lambda.
- Decimal‑safe serializer for DynamoDB types.

---

## 7) Answer API (Retrieve + Extractive Answer + Optional LLM Polish)

**Endpoint:** `POST /answer` → Lambda **`ide-answer`**  
**Purpose:** Same retrieval as `/search`, then build a concise **extractive** answer and optionally polish with **Titan Text Express**.

**Key env vars (subset)**
- Retrieval: `TABLE_NAME`, `TOP_K`, `ANSWER_SCOPE=best_doc`, `MIN_SCORE`, `MAX_SNIPPETS`, `MAX_ANSWER_CHARS`
- LLM polish: `QA_LLM_ENABLE`, `QA_LLM_MODEL_ID=amazon.titan-text-express-v1`, `QA_LLM_MAX_TOKENS`, `QA_LLM_TEMP`

**Flow**
1) Embed & score; narrow to **best doc** (configurable).  
2) Sentence picker: drops headings/ingredients/noise; boosts synonyms (*thicken, slurry, reduce*).  
3) Build `answer_raw` + `citations` (source/page/chunkId/score).  
4) If enabled, call Titan Text Express with a strict prompt to format to:
   ```
   Summary: <one sentence>
   - <bullet>
   - <bullet>
   ```
   plus sanitization to remove boilerplate.

**Response (typical)**
```json
{
  "query": "How can I thicken a thin curry sauce?",
  "answer_raw": "…",
  "answer_md": "Summary: …\n- …\n- …",
  "citations": [{"source":"s3://…","page":5,"chunkId":"0005#000005","score":0.3721}],
  "top_k": [ ... ]
}
```

---

## 8) Front‑End UX

- **Top‑K slider** (1–10) with live display; lower K = more deterministic.
- **Busy overlay** + button disable to avoid double submits; granular status messages (“Requesting upload URL…”, “Uploading…”, “OK”).
- **Same‑origin by default**; `?api=` reveals an API field to target another stage/endpoint for testing.
- Markdown answers rendered with **marked → DOMPurify**; citations shown (Score, Page, Chunk, Source).

---

## End‑to‑End Sequences

### A) Upload → Textract → Index
1. UI `POST /upload` → presigned URL & key.  
2. UI `PUT` to S3 `uploads/...`.  
3. S3 `ObjectCreated` → `ide-textract-start` → async Textract (SNS).  
4. SNS → SQS → `ide-textract-callback` → `extracted/...json`.  
5. S3 `ObjectCreated` on `extracted/…json` → `ide-embed-index` → Bedrock embed → **DynamoDB**.

### B) “Search” button
1. UI `POST /search {query, top_k}`.  
2. `ide-query` → Titan embed → table scan + cosine → return Top‑K with snippets.

### C) “Answer” button
1. UI `POST /answer {query, top_k}`.  
2. `ide-answer` → same retrieval → sentence focus → `answer_raw` + `citations`; if enabled, Titan Text Express → `answer_md`.

---

## DynamoDB Item Shape (per chunk)

- `docId` — derived from filename (sanitized).  
- `chunkId` — `"{page:04d}#{chunk_index:06d}"`.  
- `page` — page number (int).  
- `text` — chunk text (~≤800 chars).  
- `source` — `s3://bucket/key`.  
- `vec` — embedding vector (list of numbers stored as Decimal).

---

## Lambda Functions — Responsibilities

| Lambda                | Trigger / Route                     | Responsibility |
|-----------------------|-------------------------------------|----------------|
| `ide-upload-url`      | `POST /upload`                      | Validate type, return presigned S3 `PUT`, key, URI. |
| `ide-textract-start`  | S3 `uploads/` `ObjectCreated`       | Start async Textract job and wire SNS notifications. |
| `ide-textract-callback` | SQS (from SNS Textract events)    | Fetch pages via `GetDocumentTextDetection`, write `extracted/...json`. |
| `ide-embed-index`     | S3 `extracted/` `ObjectCreated`     | Chunk, embed (Titan), put items to DynamoDB. |
| `ide-query`           | `POST /search`                      | Titan embed query, scan + cosine, return Top‑K. |
| `ide-answer`          | `POST /answer`                      | Retrieval + extractive answer + optional Titan Text polish. |

---

## Security Posture (demo scale)

- **S3 private** with **OAC**; no public ACLs.  
- **CloudFront → API** behavior adds a **shared‑secret header** (Lambda authorizer validates).  
- **Uploads** restricted by presign + `ALLOWED_TYPES`.  
- **CORS** controlled by API Gateway; UI calls same‑origin by default.  
- IAM roles are scoped to minimum S3/Textract/DDB/Bedrock actions per Lambda.

---

## Future Enhancements

- Replace scan + cosine with **OpenSearch Serverless** k‑NN (SigV4 client already scaffolded in code).  
- Add document **delete** and **re‑index** tooling (bulk maintenance).  
- Warm caches, batched embeddings, and more granular CloudWatch metrics.  
- CI/CD with CDK/Terraform and per‑stage configurations.

---

## Screenshots (to add)

- `screenshots/arch-diagram.png` — System diagram.  
- `screenshots/ui-home.png` — UI landing.  
- `screenshots/upload-success.png` — Upload and status.  
- `screenshots/answer.png` — Answer view (Markdown + citations).  
- `screenshots/search.png` — Search results.

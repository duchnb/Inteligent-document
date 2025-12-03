# Intelligent Document Engine - AWS Architecture

## System Architecture Overview

![Complete Architecture](docs/screenshots/diagrams/ide-architecture.png)

The Intelligent Document Engine uses 13 AWS services orchestrated in a serverless architecture:
- **Edge Layer**: Route 53, CloudFront, ACM
- **Storage**: S3 (UI, uploads, extracted data)
- **Compute**: Lambda (6 functions)
- **API**: API Gateway (HTTP API)
- **AI/ML**: Amazon Textract, Bedrock (Titan Embed, Titan Text)
- **Messaging**: SNS, SQS
- **Database**: DynamoDB (vector storage)

---

## Data Flow Diagrams

### Flow 1: Document Upload & Processing

![Upload Processing Flow](docs/screenshots/diagrams/flow-upload-processing.png)

This flow shows the complete document ingestion pipeline:

1. **User requests upload URL** from API Gateway `/upload`
2. **Lambda generates presigned URL** for direct S3 upload
3. **User uploads file** directly to S3 `uploads/` folder
4. **S3 event triggers** `ide-textract-start` Lambda
5. **Textract async job** starts for text extraction
6. **Job completion** published to SNS topic
7. **SQS queue** buffers the event
8. **Callback Lambda** fetches Textract results
9. **Structured JSON** written to S3 `extracted/` folder
10. **S3 event triggers** `ide-embed-index` Lambda
11. **Bedrock generates embeddings** for text chunks
12. **Vectors stored** in DynamoDB with metadata

**Key Features:**
- Async processing (no timeouts)
- Event-driven architecture
- Automatic retry via SQS
- Date-partitioned storage

---

### Flow 2: Semantic Search

![Search Flow](docs/screenshots/diagrams/flow-search.png)

This flow demonstrates vector-based semantic search:

1. **User submits query** via `/search` endpoint
2. **API Gateway invokes** `ide-query` Lambda
3. **Query embedded** using Bedrock Titan Embed
4. **Vector returned** (1024 dimensions)
5. **DynamoDB scan** retrieves all document chunks
6. **Cosine similarity** computed in Lambda
7. **Top-K results** returned with scores, pages, sources

**Performance:**
- ~200-500ms for small corpora
- Table scan acceptable at demo scale
- Future: OpenSearch k-NN for production

---

### Flow 3: RAG Answer Generation

![Answer Flow](docs/screenshots/diagrams/flow-answer.png)

This flow shows the complete RAG (Retrieval-Augmented Generation) pipeline:

1. **User submits query** via `/answer` endpoint
2. **API Gateway invokes** `ide-answer` Lambda
3. **Query embedded** using Bedrock Titan Embed
4. **Vector returned** for semantic matching
5. **DynamoDB retrieval** of Top-K chunks
6. **Chunks filtered** to best document (configurable)
7. **Extractive synthesis** + optional LLM polish
8. **Bedrock Titan Text** formats to Markdown
9. **Answer + citations** returned to user

**Answer Quality:**
- Sentence-level relevance filtering
- Synonym expansion (e.g., "thicken" → "slurry", "reduce")
- Noise removal (headings, ingredients lists)
- Source attribution with confidence scores

---

## Component Details

### 1. Lambda Functions

| Function | Memory | Timeout | Trigger | Purpose |
|----------|--------|---------|---------|----------|
| **ide-upload-url** | 512 MB | 15s | API Gateway | Generate presigned S3 PUT URL |
| **ide-textract-start** | 512 MB | 30s | S3 Event | Start async Textract job |
| **ide-textract-callback** | 1024 MB | 5min | SQS | Fetch results, write JSON |
| **ide-embed-index** | 1024 MB | 5min | S3 Event | Chunk, embed, index |
| **ide-query** | 1024 MB | 30s | API Gateway | Semantic search |
| **ide-answer** | 1024 MB | 30s | API Gateway | RAG answer + polish |

### 2. AI/ML Services (Amazon Bedrock)

**Titan Embed Text v2**
- Model: `amazon.titan-embed-text-v2:0`
- Purpose: Generate embeddings for chunks & queries
- Vector dimension: 1024
- Use case: Semantic search, similarity matching

**Titan Text Express v1**
- Model: `amazon.titan-text-express-v1`
- Purpose: Polish extractive answers to Markdown
- Temperature: 0.15 (focused, deterministic)
- Max tokens: 400
- Use case: Answer formatting, summarization

### 3. Vector Storage (DynamoDB)

**Table: ide-rag**

Primary Key:
- Partition Key: `docId` (String)
- Sort Key: `chunkId` (String) - format: "PPPP#CCCCCC"

Attributes:
- `text`: Chunk content (~800 chars)
- `page`: Page number (Number)
- `source`: S3 URI (String)
- `vec`: Embedding vector (List of Decimals, 1024 dimensions)

Access Pattern:
- Query by docId for document-specific retrieval
- Scan for semantic search across all documents

---

## Security Architecture

### 1. Edge Security
- CloudFront with TLS (ACM certificate)
- Custom domain (Route 53)
- DDoS protection (AWS Shield Standard)

### 2. Storage Security
- S3 buckets: Private (no public access)
- CloudFront Origin Access Control (OAC)
- Presigned URLs for uploads (15 min expiry)

### 3. API Security
- API Gateway with CORS
- Lambda authorizer (shared secret header)
- Content-type validation

### 4. IAM Security
- Lambda execution roles (least privilege)
- S3: GetObject, PutObject (scoped to prefixes)
- DynamoDB: Query, Scan, PutItem, DeleteItem
- Textract: StartDocumentTextDetection, Get*
- Bedrock: InvokeModel (specific model ARNs)

### 5. Data Security
- S3 encryption at rest (SSE-S3)
- DynamoDB encryption at rest
- TLS in transit (all AWS service calls)

---

## Cost Optimization

### 1. CloudFront Caching
- Static UI: Cache for 1 year (immutable)
- index.html: no-cache (always fresh)
- API routes: no caching

### 2. Lambda Optimization
- Right-sized memory (512MB - 1024MB)
- Efficient code (minimal cold starts)
- Batch operations where possible

### 3. Storage Optimization
- S3 Intelligent-Tiering for extracted files
- Lifecycle policies (archive old uploads)
- DynamoDB on-demand pricing (demo scale)

### 4. Textract Optimization
- Async API (cheaper than sync)
- Text Detection only (not Analysis)
- Idempotency checks (avoid reprocessing)

### 5. Bedrock Optimization
- Titan models (cost-effective)
- Batch embeddings where possible
- Optional LLM polish (can be disabled)

---

## Monitoring & Observability

### Lambda Metrics
- Invocations, Duration, Errors, Throttles
- Custom logs with [IDE] prefix for filtering

### API Gateway Metrics
- Request count, Latency, 4XX/5XX errors
- Per-route metrics (/upload, /search, /answer)

### S3 Metrics
- Request metrics (GET, PUT)
- Storage metrics (object count, size)

### DynamoDB Metrics
- Read/Write capacity units
- Throttled requests
- Item count

### Textract Metrics
- Job success/failure rate
- Processing time
- Page count

---

## Future Enhancements

1. **OpenSearch Serverless Integration**
   - Replace DynamoDB scan with k-NN vector search
   - Faster retrieval at scale
   - Already scaffolded in code

2. **Document Management**
   - Delete API (implemented: ide-delete-doc)
   - Re-index API (implemented: ide-ingest)
   - Bulk operations

3. **Advanced Features**
   - Multi-document queries
   - Conversation history
   - Document versioning
   - User authentication (Cognito)

4. **Performance**
   - Lambda warm pools
   - Batch embedding operations
   - CloudFront edge caching
   - DynamoDB DAX for hot data

5. **CI/CD**
   - Infrastructure as Code (CDK/Terraform)
   - Automated testing
   - Multi-stage deployments
   - Blue/green deployments

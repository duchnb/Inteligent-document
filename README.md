# Intelligent Document Engine (IDE)

> **Live Demo:** [ide-doc.gitsoft.uk](https://ide-doc.gitsoft.uk)

A production-ready, serverless RAG (Retrieval-Augmented Generation) pipeline on AWS that extracts text from documents, generates embeddings, and provides intelligent question-answering with citations.

[![AWS](https://img.shields.io/badge/AWS-Serverless-orange?logo=amazon-aws)](https://aws.amazon.com/)
[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

# 📸 Screenshot Gallery (Quick Overview)

<p align="center">
  <img src="docs/screenshots/UI/User_landing_page_index.png" width="32%" />
  <img src="docs/screenshots/UI/Upload_success_card_shows_Key_and_S3_URI.png" width="32%" />
  <img src="docs/screenshots/UI/Answer_view _Polished_Markdown_and_Citations_list.png" width="32%" />
</p>

<p align="center">
  <img src="docs/screenshots/diagrams/ide-architecture.png" width="32%" />
  <img src="docs/screenshots/DynamoDB/DynamoDB_ide-rag_items.png" width="32%" />
  <img src="docs/screenshots/logs/Log_ide-answer_same_as_query_plus_LLM_amazon.titan-text-express-v1.png" width="32%" />
</p>

<p align="center">
  <img src="docs/screenshots/CloudFront/CloudFront–Distribution.png" width="32%" />
  <img src="docs/screenshots/Lambda_functions/Lambda_function_ide-answer.png" width="32%" />
  <img src="docs/screenshots/S3/Bucket_ide-bd-eu-west-2_Objects.png" width="32%" />
</p>

---

# 🧭 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [User Interface](#user-interface)
- [Backend & Monitoring](#backend--monitoring)
- [AWS Services](#aws-services)
- [Data Flows](#data-flows)
- [Technical Implementation](#technical-implementation)
- [Security](#security)
- [Performance & Cost](#performance--cost)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Testing](#testing)
- [Future Enhancements](#future-enhancements)
- [License](#license)

---

<a id="overview"></a>
## 🎯 Overview

This project demonstrates a complete end-to-end document intelligence system using AWS serverless technologies. Upload PDFs or images, ask questions, and get accurate answers with source citations—all powered by AI.

**What it does:**
- Extracts text from documents using Amazon Textract
- Generates semantic embeddings with Amazon Bedrock
- Stores vectors in DynamoDB for retrieval
- Provides intelligent answers with RAG (Retrieval-Augmented Generation)
- Polishes answers with LLM for better readability

---

<a id="key-features"></a>
## ⭐ Key Features

✅ **Document Processing**: Automatic text extraction from PDFs and images using Amazon Textract  
✅ **Semantic Search**: Vector-based retrieval using Amazon Bedrock embeddings  
✅ **Intelligent Answers**: RAG-powered responses with optional LLM polishing  
✅ **Source Citations**: Every answer includes page numbers and confidence scores  
✅ **Secure Architecture**: Private S3 buckets, OAC, presigned URLs, and IAM least privilege  
✅ **Production-Ready**: CloudFront CDN, custom domain, TLS, and comprehensive monitoring  
✅ **Event-Driven**: Async processing with SNS/SQS for reliability  
✅ **Observability**: CloudWatch logs with detailed metrics  

---

<a id="architecture"></a>
## 🏗️ Architecture

![Architecture Diagram](docs/screenshots/diagrams/ide-architecture.png)

### AWS Services Used

| Service | Purpose |
|---------|---------|
| **Route 53** | DNS management for custom domain |
| **CloudFront** | CDN for static UI and API routing |
| **ACM** | TLS/SSL certificate management |
| **S3** | Storage for UI, uploads, and extracted data |
| **API Gateway** | RESTful API endpoints |
| **Lambda** | Serverless compute (6 functions) |
| **Textract** | Document text extraction |
| **SNS/SQS** | Event-driven processing pipeline |
| **Bedrock** | AI/ML for embeddings and text generation |
| **DynamoDB** | Vector storage and retrieval |

**📖 Detailed Architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md) for comprehensive diagrams and data flows.

---

<a id="user-interface"></a>
## 🎨 User Interface

### Landing Page
![Landing Page](docs/screenshots/UI/User_landing_page_index.png)

Clean, professional interface with:
- Document upload section
- Query input with Top-K slider
- Answer/Search/Clear buttons
- Status indicators

---

### Busy Overlay
![Busy Overlay](docs/screenshots/UI/Busy_overlay_state_spinner_with_blurred_background_upload_file.png)

Visual feedback during processing:
- Semi-transparent overlay
- Animated spinner
- Status messages ("Uploading...", "Searching...")
- Disabled controls to prevent double-clicks

---

### Upload Success
![Upload Success](docs/screenshots/UI/Upload_success_card_shows_Key_and_S3_URI.png)

Confirmation card showing:
- S3 key and URI
- Content type
- Upload timestamp
- Processing status

---

### Search Results
![Search Results](docs/screenshots/UI/Search_results_view_Top-K_with_Preview.png)

Semantic search results with:
- **Cosine similarity scores** (0.0 - 1.0)
- **Page numbers** for source attribution
- **Chunk IDs** for traceability
- **Text previews** (~800 chars)
- **S3 source URIs**

---

### Answer with Citations
![Answer View](docs/screenshots/UI/Answer_view _Polished_Markdown_and_Citations_list.png)

RAG-powered answers featuring:
- **Polished Markdown** with summary and bullets
- **Citations** with scores, pages, and sources
- **Extractive synthesis** from best document
- **LLM polish** (optional) for readability

---

<a id="backend--monitoring"></a>
## 🔍 Backend & Monitoring

### CloudWatch Logs - Upload Flow
![Upload Log](docs/screenshots/logs/Log_ide-upload-url – success.png)

Presigned URL generation:
- Request validation
- URL generation with 15-min expiry
- Content-type enforcement

---

### CloudWatch Logs - Textract Start
![Textract Start](docs/screenshots/logs/log_ide-textract-start_S3_event_received_StartDocumentTextDetection_called.png)

Document processing initiation:
- S3 event received
- File validation
- Async Textract job started

---

### CloudWatch Logs - Textract Callback
![Textract Callback](docs/screenshots/logs/Log_ide-textract-callback_Job_SUCCEEDED_pages_fetched_chunks_sent_to_embed_index..png)

Text extraction completion:
- Job status: SUCCEEDED
- Pages fetched and normalized
- JSON written to S3 extracted/

---

### CloudWatch Logs - Embedding & Indexing
![Embed Index](docs/screenshots/logs/Log_ide-embed-index–batch_embeddings_write_to_DynamoDB.png)

Vector generation and storage:
- Text chunking (~800 chars)
- Bedrock embedding calls
- DynamoDB batch writes

---

### CloudWatch Logs - Query Processing
![Query Log](docs/screenshots/logs/Log_ide-query – query_embedded_similarity_scored_return_Top-K..png)

Semantic search execution:
- Query embedding
- Cosine similarity scoring
- Top-K results returned

---

### CloudWatch Logs - Answer Generation
![Answer Log](docs/screenshots/logs/Log_ide-answer_same_as_query_plus_LLM_amazon.titan-text-express-v1.png)

RAG pipeline execution:
- Semantic retrieval
- Best document selection
- Extractive synthesis
- LLM polish with Titan Text Express

---

### DynamoDB Table Structure
![DynamoDB Table](docs/screenshots/DynamoDB/DynamoDB_Table_ide-rag.png)

Vector database configuration:
- Partition key: docId
- Sort key: chunkId
- On-demand billing
- Encryption at rest

---

### DynamoDB Items
![DynamoDB Items](docs/screenshots/DynamoDB/DynamoDB_ide-rag_items.png)

Stored document chunks:
- docId, chunkId, page, text
- 1024-dimensional vectors
- Source attribution

---

### S3 Bucket - UI
![S3 UI Bucket](docs/screenshots/S3/Bucket_ide-ui-gitsoft-uk_Objects.png)

Static website hosting:
- index.html, style.v2.css, app.v2.js
- Private bucket with OAC
- CloudFront distribution

---

### S3 Bucket - Documents
![S3 Documents](docs/screenshots/S3/Bucket_ide-bd-eu-west-2_Objects.png)

Document storage:
- uploads/ folder (original PDFs)
- extracted/ folder (JSON, date-partitioned)
- Organized by YYYY/MM/DD

---

<a id="aws-services"></a>
## ☁️ AWS Services Deep Dive

### Route 53 & ACM
![Route 53](docs/screenshots/Route53_and_ACM/Route_53.png)
![ACM](docs/screenshots/Route53_and_ACM/ACM.png)

DNS and TLS management:
- Custom domain: ide-doc.gitsoft.uk
- ACM certificate (us-east-1)
- HTTPS enforcement

---

### CloudFront Distribution
![CloudFront Distribution](docs/screenshots/CloudFront/CloudFront–Distribution.png)

CDN configuration:
- Two origins (S3 UI + API Gateway)
- Custom domain with TLS
- Cache behaviors

---

### CloudFront Behaviors
![CloudFront Behaviors](docs/screenshots/CloudFront/CloudFront–Behaviours.png)

Routing rules:
- Default: S3 UI (GET)
- /upload, /search, /answer: API Gateway (POST)
- Cache policies

---

### API Gateway Routes
![API Routes](docs/screenshots/API_Gateway/API_Gateway_Routes_for_ide_API.png)

HTTP API endpoints:
- POST /upload
- POST /search
- POST /answer
- CORS enabled

---

### API Gateway Integrations
![API Integrations](docs/screenshots/API_Gateway/API_Gateway_Integrations_to_routes.png)

Lambda integrations:
- Each route mapped to specific Lambda
- Payload format version 2.0

---

### API Gateway Authorizer
![API Authorizer](docs/screenshots/API_Gateway/API_Gateway_Authorizer .png)

Security layer:
- Lambda authorizer
- Shared secret header validation

---

### Lambda Functions Overview
![Lambda Upload](docs/screenshots/Lambda_functions/Lambda_function_ide-upload-url.png)
![Lambda Textract Start](docs/screenshots/Lambda_functions/Lambda_function_ide-textract-start.png)
![Lambda Callback](docs/screenshots/Lambda_functions/Lambda_function_ide-textract-callback.png)

---

![Lambda Embed](docs/screenshots/Lambda_functions/Lambda_function_ide-embed-index.png)
![Lambda Query](docs/screenshots/Lambda_functions/Lambda_function_ide-query.png)
![Lambda Answer](docs/screenshots/Lambda_functions/Lambda_function_ide-answer.png)

Six Lambda functions handling:
- Upload URL generation
- Textract job management
- Embedding & indexing
- Search & answer generation

---

<a id="data-flows"></a>
## 🔄 Data Flows

### Flow 1: Document Upload & Processing
![Upload Flow](docs/screenshots/diagrams/flow-upload-processing.png)

12-step pipeline:
1. User requests presigned URL
2. Direct upload to S3
3. S3 event triggers Textract
4. Async text extraction
5. SNS/SQS event handling
6. JSON storage
7. Embedding generation
8. DynamoDB indexing

---

### Flow 2: Semantic Search
![Search Flow](docs/screenshots/diagrams/flow-search.png)

7-step retrieval:
1. Query embedding
2. DynamoDB scan
3. Cosine similarity
4. Top-K ranking
5. Results with metadata

---

### Flow 3: RAG Answer Generation
![Answer Flow](docs/screenshots/diagrams/flow-answer.png)

9-step RAG pipeline:
1. Query embedding
2. Semantic retrieval
3. Best document filtering
4. Extractive synthesis
5. LLM polish (optional)
6. Answer + citations

---

<a id="technical-implementation"></a>
## 🛠️ Technical Implementation

### Lambda Functions

| Function | Memory | Timeout | Trigger | Responsibility |
|----------|--------|---------|---------|----------------|
| **ide-upload-url** | 512 MB | 15s | API Gateway `/upload` | Generate presigned S3 PUT URL |
| **ide-textract-start** | 512 MB | 30s | S3 `uploads/` event | Start async Textract job |
| **ide-textract-callback** | 1024 MB | 5min | SQS (from SNS) | Fetch Textract results, write JSON |
| **ide-embed-index** | 1024 MB | 5min | S3 `extracted/` event | Chunk text, embed, store in DynamoDB |
| **ide-query** | 1024 MB | 30s | API Gateway `/search` | Semantic search with embeddings |
| **ide-answer** | 1024 MB | 30s | API Gateway `/answer` | RAG answer generation + polish |

### Data Flow

```
User Upload → S3 → Textract → SNS → SQS → Lambda → S3 (JSON)
                                                      ↓
                                            Lambda (Embed) → Bedrock → DynamoDB
                                                                          ↓
User Query → API Gateway → Lambda → Bedrock (Embed) → DynamoDB (Retrieve)
                                                          ↓
                                                    Bedrock (Polish) → Answer
```

### AI/ML Models

- **Embeddings**: `amazon.titan-embed-text-v2:0` (1024-dimensional vectors)
- **Text Generation**: `amazon.titan-text-express-v1` (optional answer polishing)

### Storage Schema (DynamoDB)

```json
{
  "docId": "Coffee-Machine-Requirements",
  "chunkId": "0005#000003",
  "page": 5,
  "text": "To thicken a thin curry sauce, simmer uncovered...",
  "source": "s3://bucket/uploads/file.pdf",
  "vec": [0.123, -0.456, ...] // 1024 dimensions
}
```

---

<a id="security"></a>
## 🔒 Security

- ✅ **Private S3 Buckets**: No public access, CloudFront OAC only
- ✅ **Presigned URLs**: Time-limited (15 min) upload URLs
- ✅ **Content-Type Validation**: Allowed types enforced
- ✅ **IAM Least Privilege**: Scoped roles per Lambda function
- ✅ **TLS Everywhere**: HTTPS via CloudFront + ACM certificate
- ✅ **CORS Control**: API Gateway CORS configuration
- ✅ **Lambda Authorizer**: Shared secret header validation

---

<a id="performance--cost"></a>
## 📊 Performance & Cost

### Performance
- **Upload**: Direct-to-S3 (no Lambda bottleneck)
- **Textract**: Async processing (handles large documents)
- **Search**: ~200-500ms for small corpora (table scan + cosine)
- **Answer**: ~1-2s (includes LLM polish)

### Cost Optimization
- CloudFront caching (static UI cached for 1 year)
- DynamoDB on-demand pricing (demo scale)
- Textract async API (cheaper than sync)
- Lambda right-sizing (512MB-1024MB)
- S3 Intelligent-Tiering for extracted files

---

<a id="project-structure"></a>
## 📁 Project Structure

```
Inteligent-document/
├── index.html                      # Main UI
├── style.v2.css                    # Styling with busy overlay
├── app.v2.js                       # Frontend logic
├── AWS Lambda functions/           # Backend functions
│   ├── ide-upload-url.py
│   ├── ide-textract-start.py
│   ├── ide-textract-callback.py
│   ├── ide-embed-index.py
│   ├── ide-query.py
│   ├── ide-answer.py
│   ├── ide-delete-doc.py
│   └── ide-ingest.py
├── docs/screenshots/               # Organized screenshots
│   ├── UI/
│   ├── diagrams/
│   ├── logs/
│   ├── Lambda_functions/
│   ├── DynamoDB/
│   ├── S3/
│   ├── CloudFront/
│   ├── API_Gateway/
│   └── Route53_and_ACM/
├── ARCHITECTURE.md                 # Detailed architecture docs
├── IDE_Technical_Presentation.md   # Technical deep-dive
└── README.md                       # This file
```

---

<a id="getting-started"></a>
## 🚦 Getting Started

### Prerequisites
- AWS Account with Bedrock access
- Python 3.9+
- AWS CLI configured
- Custom domain (optional)

### Deployment Steps

1. **Create S3 Bucket**
   ```bash
   aws s3 mb s3://<YOUR_BUCKET_NAME>
   ```

2. **Deploy Lambda Functions**
   - Create 6 Lambda functions from `AWS Lambda functions/` folder
   - Set environment variables (see inline comments in each file)
   - Attach IAM roles with appropriate permissions

3. **Configure Textract Pipeline**
   - Create SNS topic for Textract events
   - Create SQS queue subscribed to SNS
   - Set up S3 event notifications

4. **Create DynamoDB Table**
   ```bash
   aws dynamodb create-table \
     --table-name ide-rag \
     --attribute-definitions \
       AttributeName=docId,AttributeType=S \
       AttributeName=chunkId,AttributeType=S \
     --key-schema \
       AttributeName=docId,KeyType=HASH \
       AttributeName=chunkId,KeyType=RANGE \
     --billing-mode PAY_PER_REQUEST
   ```

5. **Set Up API Gateway**
   - Create HTTP API
   - Add routes: `/upload`, `/search`, `/answer`
   - Integrate with Lambda functions

6. **Configure CloudFront**
   - Create distribution with two origins (S3 + API Gateway)
   - Set up behaviors for routing
   - Add custom domain + ACM certificate

7. **Upload UI Files**
   ```bash
   aws s3 cp index.html s3://<YOUR_BUCKET_NAME>/
   aws s3 cp style.v2.css s3://<YOUR_BUCKET_NAME>/
   aws s3 cp app.v2.js s3://<YOUR_BUCKET_NAME>/
   ```

---

<a id="testing"></a>
## 🧪 Testing

### Upload a Document
```bash
curl -X POST https://ide-doc.gitsoft.uk/upload \
  -H "Content-Type: application/json" \
  -d '{"filename":"test.pdf","contentType":"application/pdf"}'
```

### Search
```bash
curl -X POST https://ide-doc.gitsoft.uk/search \
  -H "Content-Type: application/json" \
  -d '{"query":"How to thicken curry?","top_k":5}'
```

### Get Answer
```bash
curl -X POST https://ide-doc.gitsoft.uk/answer \
  -H "Content-Type: application/json" \
  -d '{"query":"How to thicken curry?","top_k":5}'
```

---

<a id="future-enhancements"></a>
## 🔮 Future Enhancements

- [ ] **OpenSearch Serverless**: Replace DynamoDB scan with k-NN vector search
- [ ] **Multi-Document Queries**: Cross-document reasoning
- [ ] **Conversation History**: Contextual follow-up questions
- [ ] **User Authentication**: Cognito integration
- [ ] **Document Versioning**: Track changes over time
- [ ] **Batch Operations**: Bulk upload and indexing
- [ ] **CI/CD Pipeline**: Infrastructure as Code (CDK/Terraform)
- [ ] **Advanced Analytics**: CloudWatch dashboards and metrics

---

<a id="license"></a>
## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📧 Contact

**Project Link**: [https://github.com/yourusername/intelligent-document-engine](https://github.com/yourusername/intelligent-document-engine)

**Live Demo**: [ide-doc.gitsoft.uk](https://ide-doc.gitsoft.uk)

---

## 🙏 Acknowledgments

- AWS for providing excellent serverless services
- Amazon Bedrock for powerful AI/ML capabilities
- The open-source community for inspiration

---

**Built with ❤️ using AWS Serverless Technologies**

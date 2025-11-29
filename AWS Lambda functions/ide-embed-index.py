Lambda Trigger
# S3: ide-bd-eu-west-2
# arn:aws:s3:::ide-bd-eu-west-2
# Details
# Bucket arn: arn:aws:s3:::ide-bd-eu-west-2
# Event types: s3:ObjectCreated:*
# isComplexStatement: No
# Notification name: 5a39385a-29b8-4eaa-9479-6f0d2422fd1e
# Prefix: extracted/
# Service principal: s3.amazonaws.com
# Source account: 519845866060
# Statement ID: lambda-e45558ec-e2bb-4acc-8ab5-fba6f67284c8
#                     Suffix: .json

# Environment variables
# BEDROCK_MODEL_ID: amazon.titan-embed-text-v2:0
# BEDROCK_REGION: eu-west-2
# MAX_CHARS_PER_CHUNK: 800
# OS_ENDPOINT: https://hq3ab9ffd7dm49qxi7mb.eu-west-2.aoss.amazonaws.com
# OS_INDEX: ide-rag
# OS_NUM_CANDIDATES: 100
# OS_SIGV4_SERVICE: aoss
# SEARCH_BACKEND: DDB
# TABLE_NAME: ide-rag

import os, json, re, math, boto3, urllib.parse
from decimal import Decimal

import json, os, urllib3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
from botocore.session import Session

_http = urllib3.PoolManager()
_region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"))
_os_endpoint = os.environ["OS_ENDPOINT"].rstrip("/")
_os_index = os.environ.get("OS_INDEX","ide-rag")
_sigv4_service = os.environ.get("OS_SIGV4_SERVICE","aoss")
_creds = Session().get_credentials().get_frozen_credentials()

def _es(method: str, path: str, body=None, params: str=""):
    url = f"{_os_endpoint}{path}{('?' + params) if params else ''}"
    data = json.dumps(body).encode("utf-8") if isinstance(body, dict) else (body or None)
    headers = {"host": _os_endpoint.replace("https://","").replace("http://",""),
               "content-type": "application/json"}
    req = AWSRequest(method=method, url=url, data=data, headers=headers)
    SigV4Auth(_creds, _sigv4_service, _region).add_auth(req)
    r = _http.request(method, url, body=data, headers=dict(req.headers))
    if r.status >= 300:
        raise RuntimeError(f"OS {method} {path} -> {r.status} {r.data[:400]!r}")
    if r.data and r.headers.get("content-type","").startswith("application/json"):
        return json.loads(r.data.decode("utf-8"))
    return None


s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
bedrock = boto3.client("bedrock-runtime", region_name=os.environ["BEDROCK_REGION"])

TABLE_NAME = os.environ["TABLE_NAME"]
MODEL_ID   = os.environ.get("BEDROCK_MODEL_ID", "amazon.titan-embed-text-v2:0")
MAX_CHARS  = int(os.environ.get("MAX_CHARS_PER_CHUNK","800"))

table = ddb.Table(TABLE_NAME)

def embed_text(text: str):
    body = json.dumps({"inputText": text})
    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    payload = json.loads(resp["body"].read())
    vec = payload.get("embedding") or payload.get("embeddings") or []
    # Convert floats → Decimals for DynamoDB
    return [Decimal(str(x)) for x in vec]

def chunk_lines(lines, max_chars=800):
    buf, size = [], 0
    for ln in lines:
        ln = (ln or "").strip()
        if not ln:
            continue
        if size + len(ln) + 1 > max_chars and buf:
            yield " ".join(buf)
            buf, size = [ln], len(ln)
        else:
            buf.append(ln)
            size += len(ln) + 1
    if buf:
        yield " ".join(buf)

def doc_id_from_source(src_key: str):
    base = os.path.basename(src_key)          # e.g. "Coffee Machine Program Requirements.pdf"
    name, _ = os.path.splitext(base)          # "Coffee Machine Program Requirements"
    return re.sub(r'[^A-Za-z0-9._-]', '-', name)[:200] or "doc"

def lambda_handler(event, context):
    for rec in event.get("Records", []):
        s3info = rec.get("s3", {})
        bucket = s3info.get("bucket", {}).get("name")
        key    = urllib.parse.unquote_plus(s3info.get("object", {}).get("key", ""))

        if not key.startswith("extracted/") or not key.endswith(".json"):
            print(f"[IDE] Skip non-extracted object: {key}")
            continue

        print(f"[IDE] Processing extracted JSON s3://{bucket}/{key}")
        j = s3.get_object(Bucket=bucket, Key=key)
        doc = json.loads(j["Body"].read())

        # Prefer source_* fields written by the callback; fallback to the key if missing
        source_bucket = doc.get("source_bucket", bucket)
        source_key    = doc.get("source_key", key)
        # NEW: stable, suffixless docId from the original upload filename
        doc_id        = doc_id_from_source(source_key)

        pages = doc.get("pages", [])
        chunk_index = 0
        puts = 0

        for page_obj in pages:
            page_no = int(page_obj.get("page", 0))
            lines   = page_obj.get("lines", [])
            for chunk in chunk_lines(lines, MAX_CHARS):
                emb = embed_text(chunk)
                item = {
                    "docId":  doc_id,
                    "chunkId": f"{page_no:04d}#{chunk_index:06d}",
                    "text":   chunk,
                    "page":   page_no,
                    "source": f"s3://{source_bucket}/{source_key}",
                    "vec":    emb
                }
                table.put_item(Item=item)
                chunk_index += 1
                puts += 1

        print(f"[IDE] Indexed {puts} chunks for docId={doc_id}")
    return {"ok": True}

# Lambda Trigger
# API Gateway: ide_API
# arn:aws:execute-api:eu-west-2:519845866060:xewso4pokf/*/*/ingest
# API endpoint: https://xewso4pokf.execute-api.eu-west-2.amazonaws.com/ingest
# Details
# API type: HTTP
# Authorization: NONE
# CORS: Yes
# Detailed metrics enabled: No
# isComplexStatement: No
# Method: ANY
# Resource path: /ingest
# Service principal: apigateway.amazonaws.com
# Stage: $default
# Statement ID: 0df1e0d7-3287-53f7-9a97-66a9cfce3a2a

# Environment variables
# BEDROCK_MODEL_ID: amazon.titan-embed-text-v2:0
# BEDROCK_REGION: eu-west-2
# MAX_CHARS_PER_CHUNK: 800
# TABLE_NAME: ide-rag


import os, json, re, base64, boto3, urllib.parse
from decimal import Decimal
from boto3.dynamodb.conditions import Key

s3   = boto3.client("s3")
ddb  = boto3.resource("dynamodb")
bedr = boto3.client("bedrock-runtime", region_name=os.environ["BEDROCK_REGION"])

TABLE_NAME = os.environ["TABLE_NAME"]
MODEL_ID   = os.environ.get("BEDROCK_MODEL_ID","amazon.titan-embed-text-v2:0")
MAX_CHARS  = int(os.environ.get("MAX_CHARS_PER_CHUNK","800"))

table  = ddb.Table(TABLE_NAME)
BUCKET = "ide-bd-eu-west-2"  # change if your bucket name differs

def embed_text(text: str):
    body = json.dumps({"inputText": text})
    resp = bedr.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    payload = json.loads(resp["body"].read())
    vec = payload.get("embedding") or payload.get("embeddings") or []
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

def make_doc_id_from_source(source_key: str):
    base = os.path.basename(source_key)
    name, _ = os.path.splitext(base)
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)[:200]
    return name or "doc"

def find_latest_extracted_key_for_source(source_key: str):
    """
    Match both:
      extracted/.../uploads/<name>.pdf.json
      extracted/.../uploads/<name>-XXXXXXXX.pdf.json   (short-id suffix)
    """
    import os
    base = os.path.basename(source_key)           # "Coffee Machine Program Requirements.pdf"
    name, ext = os.path.splitext(base)

    exact_suffix = f"/uploads/{base}.json"
    pattern = re.compile(
        rf"/uploads/{re.escape(name)}(-[0-9a-fA-F]{{8}})?{re.escape(ext)}\.json$",
        re.IGNORECASE
    )

    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    for page in paginator.paginate(Bucket=BUCKET, Prefix="extracted/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(exact_suffix) or pattern.search(key):
                if (latest is None) or obj["LastModified"] > latest["LastModified"]:
                    latest = obj

    if not latest:
        raise RuntimeError(f"No extracted JSON found for {source_key}")

    print(f"[IDE] Matched extracted key: s3://{BUCKET}/{latest['Key']}")
    return latest["Key"]

def delete_doc_items(doc_id: str):
    # query all items for docId and delete in batch
    resp = table.query(KeyConditionExpression=Key("docId").eq(doc_id))
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("docId").eq(doc_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        items += resp.get("Items", [])
    if not items:
        return 0
    count = 0
    with table.batch_writer() as bw:
        for it in items:
            bw.delete_item(Key={"docId": it["docId"], "chunkId": it["chunkId"]})
            count += 1
    return count

def index_from_extracted(bucket, extracted_key, source_bucket, source_key, doc_id):
    obj = s3.get_object(Bucket=bucket, Key=extracted_key)
    data = json.loads(obj["Body"].read())
    pages = data.get("pages", [])
    puts = 0
    chunk_index = 0
    for p in pages:
        page_no = int(p.get("page", 0))
        lines   = p.get("lines", [])
        for chunk in chunk_lines(lines, MAX_CHARS):
            emb = embed_text(chunk)
            item = {
                "docId":   doc_id,
                "chunkId": f"{page_no:04d}#{chunk_index:06d}",
                "text":    chunk,
                "page":    page_no,
                "source":  f"s3://{source_bucket}/{source_key}",
                "vec":     emb
            }
            table.put_item(Item=item)
            puts += 1
            chunk_index += 1
    return puts

def _parse_body(event):
    if "requestContext" in event and "http" in event["requestContext"]:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        return json.loads(body)
    return event if isinstance(event, dict) else {}

def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type":"application/json","access-control-allow-origin":"*"},
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    data = _parse_body(event) or {}
    source = data.get("source")
    doc_id = data.get("docId")

    if not source and not doc_id:
        return _response(400, {"error":"Provide {\"source\":\"s3://...\"} or {\"docId\":\"...\"}"})

    # If only docId given, resolve source from any existing item
    if doc_id and not source:
        resp = table.query(KeyConditionExpression=Key("docId").eq(doc_id), Limit=1)
        items = resp.get("Items", [])
        if not items:
            return _response(404, {"error": f"No items for docId={doc_id}"})
        source = items[0].get("source","")

    if not source.startswith("s3://"):
        return _response(400, {"error":"source must be s3://... uri"})

    _, rest = source.split("s3://", 1)
    src_bucket, src_key = rest.split("/", 1)

    if not doc_id:
        doc_id = make_doc_id_from_source(src_key)

    extracted_key = find_latest_extracted_key_for_source(src_key)  # date-partition aware
    deleted = delete_doc_items(doc_id)
    indexed = index_from_extracted(BUCKET, extracted_key, src_bucket, src_key, doc_id)

    return _response(200, {
        "docId": doc_id,
        "deleted": deleted,
        "indexed": indexed,
        "extracted_json": f"s3://{BUCKET}/{extracted_key}"
    })

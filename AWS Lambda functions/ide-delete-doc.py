# Lambda Trigger
# API Gateway: ide_API
# arn:aws:execute-api:eu-west-2:519845866060:xewso4pokf/*/*/delete
# API endpoint: https://xewso4pokf.execute-api.eu-west-2.amazonaws.com/delete
# Details
# API type: HTTP
# Authorization: NONE
# CORS: Yes
# Detailed metrics enabled: No
# isComplexStatement: No
# Method: ANY
# Resource path: /delete
# Service principal: apigateway.amazonaws.com
# Stage: $default
# Statement ID: c198b0ba-3df2-535d-8689-dd37028750c3

# Environment variables
# BUCKET: ide-bd-eu-west-2
# DRY_RUN: false
# EXTRACTED_PREFIX: extracted/
# TABLE_NAME: ide-rag

import os, json, re, base64, boto3
from typing import List, Set
from boto3.dynamodb.conditions import Key

TABLE_NAME      = os.environ["TABLE_NAME"]
BUCKET          = os.environ["BUCKET"]
EXTRACTED_PREF  = os.environ.get("EXTRACTED_PREFIX", "extracted/")
DRY_RUN         = os.environ.get("DRY_RUN", "false").lower() == "true"

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
s3 = boto3.client("s3")

# ---- helpers --------------------------------------------------------------

def _respond(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "access-control-allow-origin": "*"},
        "body": json.dumps(body)
    }

def _parse_event(event):
    # Supports API Gateway HTTP API and direct console test
    if "requestContext" in event and "http" in event["requestContext"]:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        return json.loads(body or "{}")
    return event if isinstance(event, dict) else {}

def doc_id_from_source(src_key: str) -> str:
    import os
    base = os.path.basename(src_key)      # e.g. "My Doc.pdf"
    name, _ = os.path.splitext(base)      # "My Doc"
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)[:200] or "doc"

def list_items_for_doc(doc_id: str):
    items = []
    resp = table.query(KeyConditionExpression=Key("docId").eq(doc_id))
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("docId").eq(doc_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        items.extend(resp.get("Items", []))
    return items

def batch_delete_items(items: List[dict]) -> int:
    if not items:
        return 0
    if DRY_RUN:
        print(f"[DRY] Would delete {len(items)} DDB items")
        return 0
    deleted = 0
    with table.batch_writer() as bw:
        for it in items:
            bw.delete_item(Key={"docId": it["docId"], "chunkId": it["chunkId"]})
            deleted += 1
    return deleted

def list_extracted_keys_for_source(source_key: str) -> List[str]:
    """
    Match both:
      extracted/.../uploads/<name>.pdf.json
      extracted/.../uploads/<name>-XXXXXXXX.pdf.json  (8-hex short tag)
    """
    import os
    base = os.path.basename(source_key)   # "My Doc.pdf"
    name, ext = os.path.splitext(base)
    exact_suffix = f"/uploads/{base}.json"
    pattern = re.compile(
        rf"/uploads/{re.escape(name)}(-[0-9a-fA-F]{{8}})?{re.escape(ext)}\.json$",
        re.IGNORECASE
    )

    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=EXTRACTED_PREF):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith(exact_suffix) or pattern.search(k):
                keys.append(k)
    return keys

def delete_s3_keys(keys: List[str]) -> int:
    if not keys:
        return 0
    if DRY_RUN:
        print(f"[DRY] Would delete {len(keys)} S3 objects")
        for k in keys: print(f"[DRY]   s3://{BUCKET}/{k}")
        return 0

    # delete in batches of 1000
    deleted = 0
    batch = []
    for k in keys:
        batch.append({"Key": k})
        if len(batch) == 1000:
            resp = s3.delete_objects(Bucket=BUCKET, Delete={"Objects": batch, "Quiet": True})
            deleted += len(resp.get("Deleted", []))
            batch = []
    if batch:
        resp = s3.delete_objects(Bucket=BUCKET, Delete={"Objects": batch, "Quiet": True})
        deleted += len(resp.get("Deleted", []))
    return deleted

# ---- handler --------------------------------------------------------------

def lambda_handler(event, context):
    data = _parse_event(event)
    # Inputs:
    #   Option A: {"docId":"..."}                -> delete DDB items for this doc + matching extracted JSON
    #   Option B: {"source":"s3://bucket/uploads/file.pdf"} -> derive docId and delete, plus extracted JSON
    #   Optional: {"deleteUploads": true}        -> also delete original uploads/<file>.pdf  (off by default)

    doc_id = (data.get("docId") or "").strip()
    source = (data.get("source") or "").strip()
    delete_uploads = bool(data.get("deleteUploads", False))

    if not doc_id and not source:
        return _respond(400, {"error": "Provide {\"docId\":\"...\"} or {\"source\":\"s3://.../uploads/file.pdf\"}"})

    # If source is given, normalize and derive docId to match your current scheme
    if source:
        if not source.startswith("s3://"):
            return _respond(400, {"error":"source must be s3://... uri"})
        _, rest = source.split("s3://", 1)
        src_bucket, src_key = rest.split("/", 1)
        if src_bucket != BUCKET:
            return _respond(400, {"error": f"source bucket must be {BUCKET}"})
        if not doc_id:
            doc_id = doc_id_from_source(src_key)
    else:
        # No source given; try to resolve it from any item for the docId
        items = list_items_for_doc(doc_id)
        if not items:
            return _respond(404, {"error": f"No items found for docId={doc_id}"})
        # grab the first non-empty source
        src = next((it.get("source") for it in items if it.get("source")), None)
        if not src:
            return _respond(404, {"error": f"Items for docId={doc_id} do not contain 'source'"})
        _, rest = src.split("s3://", 1)
        src_bucket, src_key = rest.split("/", 1)

    # 1) Delete DDB items for docId
    ddb_items = list_items_for_doc(doc_id)
    ddb_deleted = batch_delete_items(ddb_items)

    # 2) Delete extracted JSON objects for this source (all dates/variants)
    extracted_keys = list_extracted_keys_for_source(src_key)
    s3_deleted = delete_s3_keys(extracted_keys)

    # 3) (Optional) delete the original uploads file
    uploads_deleted = 0
    if delete_uploads and src_key.startswith("uploads/"):
        if DRY_RUN:
            print(f"[DRY] Would delete original upload: s3://{BUCKET}/{src_key}")
        else:
            try:
                s3.delete_object(Bucket=BUCKET, Key=src_key)
                uploads_deleted = 1
            except Exception as e:
                print("[WARN] Failed to delete upload:", repr(e))

    result = {
        "docId": doc_id,
        "ddbDeleted": ddb_deleted,
        "s3ExtractedDeleted": s3_deleted,
        "uploadsDeleted": uploads_deleted,
        "dryRun": DRY_RUN
    }
    print("[IDE] delete-doc result:", result)
    return _respond(200, result)

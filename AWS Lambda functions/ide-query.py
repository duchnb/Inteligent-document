# Lambda Trigger
# API Gateway: ide_API
# arn:aws:execute-api:eu-west-2:519845866060:xewso4pokf/*/*/search
# API endpoint: https://xewso4pokf.execute-api.eu-west-2.amazonaws.com/search
# Details
# API type: HTTP
# Authorization: NONE
# CORS: Yes
# Detailed metrics enabled: No
# isComplexStatement: No
# Method: ANY
# Resource path: /search
# Service principal: apigateway.amazonaws.com
# Stage: $default
# Statement ID: c0ad3a5a-709f-5630-9d36-6ce453d56985

# Environment variables
# BEDROCK_MODEL_ID: amazon.titan-embed-text-v2:0
# BEDROCK_REGION: eu-west-2
# OS_ENDPOINT: https://hq3ab9ffd7dm49qxi7mb.eu-west-2.aoss.amazonaws.com
# OS_INDEX: ide-rag
# OS_NUM_CANDIDATES: 100
# OS_SIGV4_SERVICE: aoss
# SEARCH_BACKEND: DDB
# TABLE_NAME: ide-rag


import os, json, math, boto3, base64
from decimal import Decimal
import urllib3
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

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["TABLE_NAME"])
bedrock = boto3.client("bedrock-runtime", region_name=os.environ["BEDROCK_REGION"])
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.titan-embed-text-v2:0")

def embed(q):
    body = json.dumps({"inputText": q})
    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    payload = json.loads(resp["body"].read())
    return payload.get("embedding") or payload.get("embeddings") or []

def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return -1.0
    num = sum(x*y for x,y in zip(a,b))
    da  = math.sqrt(sum(x*x for x in a))
    db  = math.sqrt(sum(y*y for y in b))
    return (num/(da*db)) if da and db else -1.0

def to_float_list(vec):
    return [float(v) for v in vec]

# NEW: serializer for Decimal
def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError

def _search(query, top_k=5):
    qv = embed(query)
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    scored = []
    for it in items:
        vec = it.get("vec")
        if not vec:
            continue
        score = float(cosine(qv, to_float_list(vec)))  # ensure plain float
        # page may be Decimal from DynamoDB → cast to int when present
        page_val = it.get("page")
        page_int = int(page_val) if isinstance(page_val, (int, float, Decimal)) else None

        scored.append({
            "score": score,
            "docId": it["docId"],
            "chunkId": it["chunkId"],
            "page": page_int,
            "text": it.get("text","")[:500],
            "source": it.get("source")
        })
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:top_k]

def lambda_handler(event, context):
    # HTTP API (payload v2.0)
    if "requestContext" in event and "http" in event["requestContext"]:
        try:
            body = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            data = json.loads(body)
            query = (data.get("query") or "").strip()
            if not query:
                resp = {"error": "Provide JSON body: {\"query\":\"...\"}"}
                return {
                    "statusCode": 400,
                    "headers": {
                        "content-type":"application/json",
                        "access-control-allow-origin":"*"
                    },
                    "body": json.dumps(resp)
                }
            top_k = int(data.get("top_k", 5))
            result = _search(query, top_k=top_k)
            return {
                "statusCode": 200,
                "headers": {
                    "content-type":"application/json",
                    "access-control-allow-origin":"*"
                },
                "body": json.dumps({"top_k": result}, default=_json_default)  # <-- use serializer
            }
        except Exception as e:
            print("[IDE] Error:", repr(e))
            return {
                "statusCode": 500,
                "headers": {
                    "content-type":"application/json",
                    "access-control-allow-origin":"*"
                },
                "body": json.dumps({"error":"Internal error"})
            }

    # Console/Test usage: event like {"query":"...","top_k":5}
    query = (event.get("query") or "").strip() if isinstance(event, dict) else ""
    if not query:
        return {"error": "Provide {\"query\":\"...\"} in the event."}
    top_k = int(event.get("top_k", 5))
    return {"top_k": _search(query, top_k=top_k)}

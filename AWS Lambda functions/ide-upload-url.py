
#Trigger API Gateway

# Environment variable
# ALLOWED_TYPES: application/pdf,image/png,image/jpeg
# BUCKET: ide-bd-eu-west-2
# DEFAULT_PREFIX: uploads/
# EXPIRES_IN: 900

import os, json, re, time, uuid, base64, boto3



s3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
PREFIX = os.environ.get("DEFAULT_PREFIX", "uploads/")
EXPIRES = int(os.environ.get("EXPIRES_IN", "900"))
ALLOWED = set((os.environ.get("ALLOWED_TYPES") or "application/pdf,image/png,image/jpeg").split(","))

def _res(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type":"application/json", "access-control-allow-origin":"*"},
        "body": json.dumps(body)
    }

def _parse(event):
    if "requestContext" in event and "http" in event["requestContext"]:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"): body = base64.b64decode(body).decode("utf-8")
        return json.loads(body)
    return event if isinstance(event, dict) else {}

def _safe_name(name: str) -> str:
    name = name.strip() or "file"
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    return name[:200]

def lambda_handler(event, context):
    data = _parse(event)
    filename = _safe_name(data.get("filename") or "file.pdf")
    ctype = (data.get("contentType") or "application/pdf").strip().lower()

    if ALLOWED and ctype not in ALLOWED:
        return _res(400, {"error": f"Unsupported contentType. Allowed: {sorted(ALLOWED)}"})

    key = f"{PREFIX}{int(time.time())}-{uuid.uuid4().hex[:8]}-{filename}"
    url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": ctype},
        ExpiresIn=EXPIRES
    )
    return _res(200, {
        "uploadUrl": url,
        "key": key,
        "s3Uri": f"s3://{BUCKET}/{key}",
        "contentType": ctype,
        "expiresIn": EXPIRES
    })

# Lambda Trigger
# SQS: ide-textract-events
# arn:aws:sqs:eu-west-2:519845866060:ide-textract-events
# state: Enabled
# Details
# Activate trigger: Yes
# Batch size: 1
# Batch window: None
# Event source mapping ARN: arn:aws:lambda:eu-west-2:519845866060:event-source-mapping:c484334e-8c5d-4f80-808c-7d23b76bcbf6
# Metrics: None
# On-failure destination: None
# Report batch item failures: No
# Tags: View

# Environment variables
# OUTPUT_BUCKET: ide-bd-eu-west-2
# OUTPUT_PREFIX: extracted/

import os, json, boto3, urllib.parse, botocore, re
from datetime import datetime, timezone

s3 = boto3.client("s3")
textract = boto3.client("textract")

OUT_BUCKET = os.environ["OUTPUT_BUCKET"]
OUT_PREFIX = os.environ.get("OUTPUT_PREFIX","extracted/")

def _safe_out_key(src_bucket, src_key, job_id):
    base = os.path.basename(src_key)
    name, _ = os.path.splitext(base)
    safe = re.sub(r'[^A-Za-z0-9._-]', '-', name)           # keep filename readable & safe
    date = datetime.now(timezone.utc).strftime('%Y/%m/%d') # "YYYY/MM/DD"
    short = (job_id or "job")[:8]                          # short unique suffix
    # Keeps the original 'uploads/' subpath (nice for traceability). Remove it if you want a flat layout.
    return f"{OUT_PREFIX}{date}/{src_key}.json".replace(".pdf.json", f"-{short}.pdf.json")

def _parse_textract_sns_record(sqs_record):
    """
    Returns: status, job_id, bucket, key, job_tag, api
    All may be None except status & job_id; we defensively handle missing values.
    """
    body = json.loads(sqs_record["body"])

    # SQS->SNS envelope: SQS body has "Message" which is the SNS message payload (stringified JSON)
    sns_msg = json.loads(body["Message"]) if isinstance(body.get("Message"), str) else body
    # Helpful to see what we actually got (truncated)
    try:
        print("[DEBUG] SNS message (truncated):", json.dumps(sns_msg, default=str)[:2000])
    except Exception:
        pass

    # Core fields (many shapes use these exact keys)
    status = sns_msg.get("Status") or sns_msg.get("status")
    job_id = sns_msg.get("JobId") or sns_msg.get("jobId")
    job_tag = sns_msg.get("JobTag") or sns_msg.get("jobTag")
    api = sns_msg.get("API") or sns_msg.get("Api") or sns_msg.get("api")

    # Document location can vary. Try the common dict shape first.
    bucket = None
    key = None
    docloc = sns_msg.get("DocumentLocation")

    if isinstance(docloc, dict):
        # Most common shape for StartDocumentTextDetection
        bucket = docloc.get("S3Bucket") or docloc.get("Bucket")
        key    = docloc.get("S3ObjectName") or docloc.get("Name") or docloc.get("Key")
    elif isinstance(docloc, str):
        # Sometimes given as "s3://bucket/key"
        if docloc.startswith("s3://"):
            # split "s3://bucket/key/with/slashes"
            path = docloc[5:]  # drop "s3://"
            parts = path.split("/", 1)
            if len(parts) == 2:
                bucket, key = parts[0], parts[1]

    # Extra fallbacks some payloads have
    bucket = bucket or sns_msg.get("S3Bucket") or sns_msg.get("Bucket")
    key    = key    or sns_msg.get("S3ObjectName") or sns_msg.get("ObjectName") or sns_msg.get("Key") or sns_msg.get("Name")

    return status, job_id, bucket, key, job_tag, api

def lambda_handler(event, context):
    for rec in event.get("Records", []):
        status, job_id, bucket, key, job_tag, api = _parse_textract_sns_record(rec)
        print(f"[IDE] Parsed -> status={status} job_id={job_id} api={api} bucket={bucket} key={key} job_tag={job_tag}")

        if not job_id:
            print("[IDE] Missing JobId in SNS message; skipping.")
            continue

        if status != "SUCCEEDED":
            print(f"[IDE] JobId={job_id} not successful (status={status}). Skipping.")
            continue

        out_key = _safe_out_key(bucket, key, job_id)

        # Idempotency: if output already exists, skip
        try:
            s3.head_object(Bucket=OUT_BUCKET, Key=out_key)
            print(f"[IDE] Output exists s3://{OUT_BUCKET}/{out_key} ; skipping.")
            continue
        except botocore.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") != "404":
                raise  # only ignore Not Found

        # Page through results
        pages = {}
        next_token = None
        while True:
            kwargs = {"JobId": job_id, "MaxResults": 1000}
            if next_token:
                kwargs["NextToken"] = next_token
            resp = textract.get_document_text_detection(**kwargs)
            for b in resp.get("Blocks", []):
                if b.get("BlockType") == "LINE":
                    p = b.get("Page", 1)
                    pages.setdefault(p, []).append(b.get("Text", ""))
            next_token = resp.get("NextToken")
            if not next_token:
                break

        ordered = [{"page": p, "lines": pages[p]} for p in sorted(pages)]
        payload = {
            "source_bucket": bucket,
            "source_key": key,
            "job_id": job_id,
            "job_tag": job_tag,
            "api": api,
            "pages": ordered
        }

        s3.put_object(
            Bucket=OUT_BUCKET,
            Key=out_key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json"
        )
        print(f"[IDE] Wrote s3://{OUT_BUCKET}/{out_key}")

    return {"ok": True}

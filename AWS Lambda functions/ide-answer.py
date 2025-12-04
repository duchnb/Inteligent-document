# Lambda trigger
# API Gateway: ide_API
# arn:aws:execute-api:<YOUR_REGION>:<YOUR_ACCOUNT_ID>:<YOUR_API_ID>/*/*/answer
# API endpoint: https://<YOUR_API_ID>.execute-api.<YOUR_REGION>.amazonaws.com/answer
# Details
# API type: HTTP
# Authorization: NONE
# CORS: Yes
# Detailed metrics enabled: No
# isComplexStatement: No
# Method: ANY
# Resource path: /answer
# Service principal: apigateway.amazonaws.com
# Stage: $default
# Statement ID: d2186751-1452-520c-92cb-e611d749a9f8

# Environment variables
# ANSWER_SCOPE: best_doc
# BEDROCK_MODEL_ID: amazon.titan-embed-text-v2:0
# BEDROCK_REGION: eu-west-2
# MAX_ANSWER_CHARS: 800
# MAX_SNIPPETS: 2
# MIN_SCORE: 0.35
# OS_ENDPOINT: https://<YOUR_OPENSEARCH_ENDPOINT>.aoss.amazonaws.com
# OS_INDEX: ide-rag
# OS_NUM_CANDIDATES: 100
# OS_SIGV4_SERVICE: aoss
# QA_LLM_ENABLE: true
# QA_LLM_MAX_TOKENS: 400
# QA_LLM_MODEL_ID: amazon.titan-text-express-v1
# QA_LLM_TEMP: 0.15
# SEARCH_BACKEND: DDB
# TABLE_NAME: ide-rag
# TOP_K: 5

import os, json, math, boto3, base64, re
from decimal import Decimal

import urllib3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
from botocore.session import Session

# ---------- HTTP + SigV4 (for OpenSearch Serverless if/when used) ----------
_http = urllib3.PoolManager()
_region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"))
_os_endpoint = os.environ["OS_ENDPOINT"].rstrip("/") if os.environ.get("OS_ENDPOINT") else ""
_os_index = os.environ.get("OS_INDEX", "ide-rag")
_sigv4_service = os.environ.get("OS_SIGV4_SERVICE", "aoss")
_creds = Session().get_credentials().get_frozen_credentials()

# ---------- LLM polish config ----------
QA_LLM_ENABLE   = os.environ.get("QA_LLM_ENABLE","false").lower() == "true"
# Default to Titan Text Express (RAG-friendly, no Anthropic form needed)
QA_LLM_MODEL_ID = os.environ.get("QA_LLM_MODEL_ID","amazon.titan-text-express-v1")
QA_LLM_TEMP     = float(os.environ.get("QA_LLM_TEMP","0.2"))
QA_LLM_MAXTOK   = int(os.environ.get("QA_LLM_MAX_TOKENS","400"))

SYSTEM_PROMPT = (
    "Rewrite the given ANSWER into concise Markdown for a user.\n"
    "Produce ONLY:\n"
    "Summary: <one sentence>\n"
    "- <bullet 1>\n"
    "- <bullet 2> (optional)\n"
    "\n"
    "Do NOT include any sections named 'Rules' or 'Output'. "
    "Do NOT invent new facts. Keep ≤120 words."
)

STOPWORDS = {
    "a","an","the","and","or","but","if","then","else","when","what","which",
    "who","whom","whose","is","are","was","were","be","been","being",
    "do","does","did","doing","can","could","may","might","must","shall","should","will","would",
    "to","of","in","on","at","by","for","from","with","without","within","about","over","under",
    "after","before","during","as","that","this","these","those","i","you","he","she","it","we",
    "they","me","him","her","us","them","my","your","his","her","its","our","their","how"
}

# ---------- Answer synthesis tuning ----------
ANSWER_SCOPE  = os.environ.get("ANSWER_SCOPE", "best_doc")  # best_doc | all_docs
MIN_SCORE     = float(os.environ.get("MIN_SCORE", "0.25"))  # drop weak chunks
MAX_SNIPPETS  = int(os.environ.get("MAX_SNIPPETS", "4"))    # sentences in answer
MAX_ANSWER    = int(os.environ.get("MAX_ANSWER_CHARS", "800"))

# ---------- Bedrock / DDB ----------
ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["TABLE_NAME"])
bedrock = boto3.client("bedrock-runtime", region_name=os.environ["BEDROCK_REGION"])

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.titan-embed-text-v2:0")
TOP_K    = int(os.environ.get("TOP_K", "5"))

def enforce_summary_line(md: str) -> str:
    lines = [ln for ln in (md or "").splitlines()]
    # find first non-empty line
    i = next((idx for idx,ln in enumerate(lines) if ln.strip()), None)
    if i is None:
        return md
    first = lines[i].lstrip()
    if first.startswith("- "):  # convert first bullet → Summary
        sentence = re.sub(r"^\-\s*", "", first).strip()
        if sentence and not sentence.endswith("."):
            sentence += "."
        lines[i] = f"Summary: {sentence}"
    return "\n".join(lines)

# ---------- Utility: JSON default ----------
def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError

# ---------- Markdown sanitizer for LLM output ----------
def sanitize_markdown(md: str) -> str:
    lines = [ln.strip() for ln in (md or "").splitlines()]
    drop_prefixes = (
        "here is", "keep in mind", "note:", "this model",
        "the summary", "json context", "output strictly"
    )
    out = []
    for ln in lines:
        low = ln.lower()
        if any(low.startswith(p) for p in drop_prefixes):
            continue
        out.append(ln)

    # collapse multiple blank lines
    res, prev_blank = [], False
    for ln in out:
        if ln == "" and prev_blank:
            continue
        res.append(ln)
        prev_blank = (ln == "")

    # prefer bullet dashes over numbered items
    res2 = [re.sub(r'^\s*\d+\.\s+', '- ', ln) for ln in res]
    return "\n".join(res2).strip()

# ---------- LLM polish ----------
def polish_with_llm(raw_answer: str, citations: list) -> str:
    """
    Uses Titan Text (amazon.titan-text-*) if selected; supports Anthropic if you switch later.
    """
    ctx = {"answer": raw_answer, "citations": citations}
    mid = QA_LLM_MODEL_ID

    # Titan Text request/response
    if mid.startswith("amazon.titan-text"):
        body = {
            "inputText": (
                    SYSTEM_PROMPT
                    + "\n\nJSON CONTEXT (use only this content):\n"
                    + json.dumps(ctx, ensure_ascii=False)
            ),
            "textGenerationConfig": {
                "temperature": QA_LLM_TEMP,
                "topP": 0.9,
                "maxTokenCount": QA_LLM_MAXTOK,
                "stopSequences": []
            }
        }
        resp = bedrock.invoke_model(
            modelId=mid,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body).encode("utf-8")
        )
        out = json.loads(resp["body"].read())
        results = out.get("results") or []
        md = ""
        if results and isinstance(results[0], dict):
            md = (results[0].get("outputText") or "").strip()
        md = sanitize_markdown(md)
        md = enforce_summary_line(md)   # ← added
        return md or raw_answer

    # Anthropic (fallback)
    if mid.startswith("anthropic."):
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role":"user","content":[{"type":"text","text": json.dumps(ctx, ensure_ascii=False)}]}
            ],
            "max_tokens": QA_LLM_MAXTOK,
            "temperature": QA_LLM_TEMP
        }
        resp = bedrock.invoke_model(
            modelId=mid,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body).encode("utf-8")
        )
        out = json.loads(resp["body"].read())
        parts = out.get("content", []) or []
        text_parts = [p.get("text","") for p in parts if isinstance(p, dict)]
        text = ("\n".join(text_parts).strip())
        md = sanitize_markdown(text)
        md = enforce_summary_line(md)   # ← added
        return md or raw_answer

    # Unknown provider → raw
    return raw_answer

def maybe_polish_answer(raw_answer: str, citations: list) -> str:
    if not QA_LLM_ENABLE:
        return raw_answer
    if not raw_answer or not isinstance(raw_answer, str) or not raw_answer.strip():
        return raw_answer  # nothing to rewrite
    try:
        return polish_with_llm(raw_answer, citations)
    except Exception as e:
        print("[IDE] LLM polish failed, falling back:", repr(e))
        return raw_answer

# ---------- OpenSearch helper (kept for later wiring) ----------
def _es(method: str, path: str, body=None, params: str=""):
    if not _os_endpoint:
        raise RuntimeError("OS_ENDPOINT not configured")
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

# ---------- Embeddings & utils ----------
def embed(text: str):
    body = json.dumps({"inputText": text})
    resp = bedrock.invoke_model(modelId=MODEL_ID,
                                contentType="application/json",
                                accept="application/json",
                                body=body)
    payload = json.loads(resp["body"].read())
    return payload.get("embedding") or payload.get("embeddings") or []

def cosine(a, b):
    if not a or not b or len(a) != len(b): return -1.0
    num = sum(x*y for x,y in zip(a,b))
    da  = math.sqrt(sum(x*x for x in a))
    db  = math.sqrt(sum(y*y for y in b))
    return (num/(da*db)) if da and db else -1.0

def to_float_list(vec):
    return [float(x) for x in vec]

def scan_all_items():
    items, resp = [], table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items

# ---------- Text heuristics ----------
EXCLUDE_PREFIXES = ("contents","glossary","faq","ingredients","serves","prep","cook")

def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s and s.strip()]

def is_heading_or_noise(s: str) -> bool:
    ls = (s or "").lower().strip()

    # obvious headings / sections
    if any(ls.startswith(p) for p in EXCLUDE_PREFIXES):
        return True

    # drop question-only stubs like "Tips Too thin?"
    if ls.endswith("?") and (ls.startswith("tips") or len(ls.split()) <= 4):
        return True

    # lines that contain section meta very early (e.g., "... Serves 4 Prep 10 ...")
    if re.search(r"\b(serves|prep|cook|ingredients)\b", ls[:60] or ""):
        return True

    # enumerated section headers like "3) Weeknight Chicken Curry ..."
    if re.match(r"^\d+\)\s+[A-Za-z]", ls or ""):
        return True

    # raw "Ingredients ..." lists or lines with lots of commas (likely ingredient enumerations)
    if "ingredients" in ls or (ls.count(",") >= 6 and "tip" not in ls):
        return True

    # very short / formatting noise
    if len(ls) < 5:
        return True

    return False

def expand_terms(q: str):
    ql = (q or "").lower(); adds = set()
    if "thicken" in ql or "thin curry" in ql or "thicker" in ql or ("thin" in ql and "sauce" in ql):
        adds |= {
            "thicken","thickened","reduce","reduction","simmer uncovered",
            "slurry","cornflour","corn flour","cornstarch","arrowroot","roux"
        }
    if "dairy" in ql:
        adds |= {"dairy-free","plant milk","oat","almond","oil","butter"}
    if "split" in ql or "dressing" in ql:
        adds |= {"split","broken","emulsify","mustard","whisk"}
    return adds

def needs_focus_gate(query: str) -> bool:
    ql = (query or "").lower()
    return ("thicken" in ql) or ("thin" in ql and "sauce" in ql)

def pick_sentences_focus(query, texts, limit_chars=800):
    # tokenize query and drop stopwords
    q_terms  = {t for t in re.findall(r"[A-Za-z0-9]+", (query or "").lower()) if t not in STOPWORDS}
    syn_terms = expand_terms(query)
    gate = needs_focus_gate(query)

    def relevance(s):
        ls = (s or "").lower()
        q_hit   = sum(t in ls for t in q_terms)
        syn_hit = sum(t in ls for t in syn_terms)
        # require at least one synonym hit if the query is about thickening
        if gate and syn_hit == 0:
            return 0
        # weight synonym matches higher than plain query term matches
        return (2 * syn_hit) + q_hit

    # collect candidates
    cand = []
    for t in texts:
        for s in split_sentences(t):
            if is_heading_or_noise(s):
                continue
            r = relevance(s)
            if r > 0:
                cand.append((r, len(s), s))

    if not cand:
        for t in texts:
            for s in split_sentences(t):
                if not is_heading_or_noise(s):
                    return s[:limit_chars]
        return (texts[0] or "")[:limit_chars] if texts else ""

    # sort: higher relevance first, then shorter sentences preferred
    cand.sort(key=lambda x: (x[0], -x[1]), reverse=True)

    # build output with simple de-duplication (case/space-insensitive)
    out, used, count, seen = [], 0, 0, set()
    for r, ln, s in cand:
        norm = re.sub(r"\s+", " ", s.strip().lower())
        if norm in seen:
            continue
        if count >= MAX_SNIPPETS or used + len(s) + 1 > limit_chars:
            break
        out.append(s)
        used += len(s) + 1
        count += 1
        seen.add(norm)

    return " ".join(out)

# ---------- HTTP response ----------
def respond(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*"
        },
        "body": json.dumps(body, default=_json_default)
    }

# ---------- Handler ----------
def lambda_handler(event, context):
    # HTTP (API Gateway v2.0)
    if "requestContext" in event and "http" in event["requestContext"]:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        try:
            data = json.loads(body)
        except Exception:
            return respond(400, {"error": "Body must be JSON"})

        query = (data.get("query") or "").strip()
        top_k = int(data.get("top_k", TOP_K))
        if not query:
            return respond(400, {"error": "Provide JSON body: {\"query\":\"...\"}"})

        # 1) Embed the question
        qv = embed(query)

        # 2) Retrieve all chunks and score (small corpora → full table scan)
        items = scan_all_items()
        scored = []
        for it in items:
            vec = it.get("vec")
            if not vec:
                continue
            score = cosine(qv, to_float_list(vec))
            scored.append({
                "score": float(score),
                "docId": it["docId"],
                "chunkId": it["chunkId"],
                "page": int(it.get("page")) if it.get("page") is not None else None,
                "text": it.get("text",""),
                "source": it.get("source")
            })
        top = sorted(scored, key=lambda x: x["score"], reverse=True)[:top_k]

        # --- DEBUG: top-k overview ---
        try:
            print("[IDE] top_k count:", len(top))
            print("[IDE] top_k scores:", [round(float(t.get("score",0.0)), 4) for t in top])
            print("[IDE] top_k docIds:", list({t.get("docId") for t in top}))
        except Exception as e:
            print("[IDE] debug(top) failed:", repr(e))

        # 3) Focus on the *best* document (cleaner answers)
        best_doc = top[0]["docId"] if top else None
        if ANSWER_SCOPE == "best_doc" and best_doc:
            filtered = [t for t in top if t["docId"] == best_doc and t["score"] >= MIN_SCORE]
            if not filtered:
                filtered = top[:1]
        else:
            filtered = [t for t in top if t["score"] >= MIN_SCORE] or top[:1]

        # --- DEBUG: filtered view ---
        try:
            print("[IDE] best_doc:", best_doc)
            print("[IDE] filtered_count:", len(filtered))
            print("[IDE] filtered_scores:", [round(float(t.get("score",0.0)), 4) for t in filtered])
        except Exception as e:
            print("[IDE] debug(filtered) failed:", repr(e))

        # 4) Build focused extractive answer + citations
        answer = pick_sentences_focus(query, [t["text"] for t in filtered], limit_chars=MAX_ANSWER)
        citations = [
            {"source": t["source"], "page": t["page"], "chunkId": t["chunkId"], "score": t["score"]}
            for t in filtered
        ]

        # --- guarantee a non-empty answer_raw (thematic fallback) ---
        if not isinstance(answer, str) or not answer.strip():
            answer = ""
            thick_kw = re.compile(
                r"\b(thicken|thickened|slurry|corn\s*flour|cornflour|cornstarch|arrowroot|roux|reduce|simmer\s+uncovered)\b",
                re.I,
            )
            for t in filtered:
                for s in split_sentences(t.get("text") or ""):
                    if is_heading_or_noise(s):
                        continue
                    if thick_kw.search(s):
                        answer = s
                        break
                if answer:
                    break
            if not answer and filtered:
                answer = (filtered[0].get("text") or "")[:MAX_ANSWER]

        # --- DEBUG: answer + LLM status ---
        try:
            print("[IDE] LLM:", QA_LLM_MODEL_ID, "enabled:", QA_LLM_ENABLE)
            print("[IDE] answer_raw_len:", len(answer or ""))
            print("[IDE] citations(min):", [{"p": c.get("page"), "chunk": c.get("chunkId")} for c in citations])
        except Exception as e:
            print("[IDE] debug(answer) failed:", repr(e))

        # 5) Optional LLM polish → Markdown (falls back to raw if disabled or fails)
        pretty_md = maybe_polish_answer(answer, citations)

        # Final payload (both raw + polished)
        payload = {
            "query": query,
            "answer_raw": answer or "",
            "answer_md":  pretty_md,
            "citations":  citations,
            "top_k":      top
        }
        return respond(200, payload)

    # Console test path
    query = (event.get("query") or "").strip() if isinstance(event, dict) else ""
    if not query:
        return {"error": "Provide {\"query\":\"...\"} in the event."}
    api_evt = {"requestContext":{"http":{}}, "body": json.dumps({"query": query, "top_k": event.get("top_k", TOP_K)})}
    return lambda_handler(api_evt, context)


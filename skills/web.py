# name: web
# description: Access the internet. {"action":"search","query":"…"} returns top web results (title, url, snippet) from DuckDuckGo. {"action":"fetch","url":"https://…"} downloads a page and returns its readable text. {"action":"answer","query":"…"} gives a quick instant-answer summary. Use search to find things, then fetch to read a specific page.
import json
import re
import urllib.request
import urllib.parse

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    enc = "utf-8"
    ctype = resp.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        enc = m.group(1)
    return raw.decode(enc, errors="replace")


def _strip_html(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|h[1-6]|li|tr)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text).replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _search(query):
    if not query.strip():
        return {"ok": False, "error": "search needs a query"}
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        html = _get(url)
    except Exception as e:
        return {"ok": False, "error": f"search failed: {e}"}
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, title = m.group(1), _strip_html(m.group(2))
        if "duckduckgo.com/y.js" in href or "ad_domain" in href:
            continue   # skip sponsored/ad results
        # DuckDuckGo wraps links in a redirect with the real URL in uddg=
        q = urllib.parse.urlparse(href).query
        real = urllib.parse.parse_qs(q).get("uddg", [href])[0]
        results.append({"title": title.strip(), "url": real})
        if len(results) >= 8:
            break
    # snippets
    snips = [_strip_html(s) for s in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)]
    for i, s in enumerate(snips[:len(results)]):
        results[i]["snippet"] = s[:240]
    if not results:
        return {"ok": False, "error": "no results (DuckDuckGo may have changed its page)"}
    return {"ok": True, "result": results}


def _answer(query):
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    try:
        data = json.loads(_get(url))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    text = data.get("AbstractText") or data.get("Answer") or ""
    if not text and data.get("RelatedTopics"):
        first = data["RelatedTopics"][0]
        text = first.get("Text", "") if isinstance(first, dict) else ""
    if not text:
        return {"ok": False, "error": "no instant answer — try action 'search'"}
    return {"ok": True, "result": {"answer": text, "source": data.get("AbstractURL", "")}}


def _fetch(url):
    if not url.strip():
        return {"ok": False, "error": "fetch needs a url"}
    if not url.startswith("http"):
        url = "https://" + url
    try:
        html = _get(url, timeout=25)
    except Exception as e:
        return {"ok": False, "error": f"couldn't fetch: {e}"}
    title = ""
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if m:
        title = _strip_html(m.group(1))
    text = _strip_html(html)
    return {"ok": True, "result": {"title": title, "url": url, "text": text[:9000]}}


def run(args):
    action = str(args.get("action", "search")).lower()
    if action == "search":
        return _search(str(args.get("query", "")))
    if action == "answer":
        return _answer(str(args.get("query", "")))
    if action in ("fetch", "open", "read", "get"):
        return _fetch(str(args.get("url", "") or args.get("query", "")))
    return {"ok": False, "error": "action must be search, answer, or fetch"}

import os, re, json, time, random, urllib.parse, warnings, datetime, sys, asyncio, uuid, hashlib
from pathlib import Path
from threading import Thread
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --- LLM (identique à ton notebook)
from langchain_openai.chat_models import AzureChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

# --- DOCX
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Cm

# --- Playwright
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ------------------------------------------------------------
# Préparation env & constantes (identiques)
# ------------------------------------------------------------
load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

HEADERS = {"User-Agent": "Mozilla/5.0"}
SIMPLE_HEADERS = {"User-Agent": "Mozilla/5.0"}
ADVANCED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0"
}

PRODUCT_PATTERNS = [
    re.compile(r"https?://(?:www\.)?pointp\.fr/p/.+-A\d+(?:[/?#].*)?$", re.I),
    re.compile(r"https?://(?:www\.)?cedeo\.fr/p/.+-A\d+(?:[/?#].*)?$", re.I),
    re.compile(r"https?://(?:www\.)?se\.com/.*/product/[A-Za-z0-9_-]+(?:[/?#].*)?$", re.I),
    re.compile(r"https?://(?:www\.)?se\.com/[a-z]{2}/[a-z]{2}/product/[A-Za-z0-9_-]+(?:[/?].*)?$", re.I),
    re.compile(r"https?://(?:www\.)?se\.com/.*/product/[A-Za-z0-9_-]+(?:[/?].*)?$", re.I),
    re.compile(r"https?://(?:www\.)?pointp\.fr/.*", re.I),
    re.compile(r"https?://(?:www\.)?cedeo\.fr/.*", re.I),
    re.compile(r"https?://(?:www\.)?se\.com/.*", re.I)
]

CANDIDATE_LABELS = [
    r"\bsans\s*prix\b",
    r"\btout\s*télécharger\b",
    r"\btélécharger\b",
    r"\btélécharger\s*sans\s*prix\b",
    r"\bdownload\b",
    r"\btechnical\s*sheet\b",
    r"\bfiche\s*technique\b",
    r"\bfiche\s*produit\b",
    r"\bnotice\b",
    r"\bimprimer\s*sans\s*prix\b",
    r"\bcatalogue\b",
    r"\bfiche\s*technique\s*du\s*produit\b",
    r"\bimprimer\s*sans\s*prix\b",
    r"\bprofil\s*environnemental\b",
]
SE_COM_LABELS = [
    r"\bfiche\s*technique\s*du\s*produit\b",
    r"\bfiche\s*technique\b",
    r"\bfiche\s*produit\b",
    r"\btout\s*télécharger\b",
    r"\btélécharger\b",
    r"\bdocumentation\b",
]
CEDEO_LABELS = [
    r"\bsans\s*prix\b",
    r"\bimprimer\s*sans\s*prix\b",
    r"\btélécharger\s*sans\s*prix\b",
    r"\bfiche\s*produit\b",
    r"\bfiche\s*technique\b",
    r"\bdocumentation\b",
    r"\bnotice\b",
    r"\bFDS\b|\bfiche\s*de\s*sécurité\b",
    r"\btélécharger\b",
]
COOKIE_ACCEPT_LABELS = [
    r"tout accepter", r"accepter", r"j.?accepte", r"ok", r"continuer sans accepter",
    r"accept all", r"agree", r"allow all", r"necessary only", r"confirm your choices",
    r"accept & close", r"accepter & fermer"
]

# ------------------------------------------------------------
# Search (reprend ton code)
# ------------------------------------------------------------
def is_product_url(u: str, domains: List[str]) -> bool:
    dynamic_product_patterns = []
    for d in domains:
        if d == "se.com":
            # More flexible patterns for se.com
            dynamic_product_patterns.append(re.compile(r"https?://(?:www\.)?se\.com/.*/product/[A-Za-z0-9_-]+(?:[/?#].*)?$", re.I))
            dynamic_product_patterns.append(re.compile(r"https?://(?:www\.)?se\.com/[a-z]{2}/[a-z]{2}/product/[A-Za-z0-9_-]+(?:[/?].*)?$", re.I))
            dynamic_product_patterns.append(re.compile(r"https?://(?:www\.)?se\.com/.*/product/[A-Za-z0-9_-]+(?:[/?].*)?$", re.I))
            dynamic_product_patterns.append(re.compile(r"https?://(?:www\.)?se\.com/.*", re.I))
        else:
            # General pattern for other domains
            dynamic_product_patterns.append(re.compile(rf"https?://(?:www\.)?{re.escape(d)}/p/.+-A\d+(?:[/?#].*)?$", re.I))
            dynamic_product_patterns.append(re.compile(rf"https?://(?:www\.)?{re.escape(d)}/.*", re.I))
    return any(p.search(u) for p in dynamic_product_patterns)

def decode_ddg_redirect(u: str) -> str:
    if not u:
        return u
    if u.startswith("//"):
        u = "https:" + u
    parsed = urllib.parse.urlparse(u)
    q = urllib.parse.parse_qs(parsed.query)
    return urllib.parse.unquote(q["uddg"][0]) if "uddg" in q else u

def ddg_product_urls(query: str, domains, max_results=10):
    site_filter = " OR ".join(f"site:{d}" for d in domains)
    q = f"{query} {site_filter}"

    sess = requests.Session()
    sess.headers.update(HEADERS)
    tried = []

    # 1) DDG HTML via POST
    for url in ("https://duckduckgo.com/html/", "https://html.duckduckgo.com/html/"):
        try:
            r = sess.post(url, data={"q": q}, verify=False, timeout=15)
            tried.append((url, r.status_code))
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for a in soup.select("a.result__a"):
                real = decode_ddg_redirect(a.get("href"))
                if is_product_url(real, domains):
                    results.append((a.get_text(strip=True) or real, real))
                if len(results) >= max_results:
                    break
            if results:
                return results, tried
        except Exception as e:
            tried.append((url, repr(e)))

    # 2) Lite fallback via GET
    for url in (
        f"https://duckduckgo.com/lite/?q={urllib.parse.quote_plus(q)}",
        f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote_plus(q)}",
    ):
        try:
            r = sess.get(url, verify=False, timeout=15)
            tried.append((url, r.status_code))
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for a in soup.select("a[href]"):
                real = decode_ddg_redirect(a.get("href"))
                if is_product_url(real, domains):
                    title = a.get_text(strip=True) or real
                    results.append((title, real))
                if len(results) >= max_results:
                    break
            if results:
                return results, tried
        except Exception as e:
            tried.append((url, repr(e)))

    return [], tried

def pick_best_result(results, keywords):
    scored = []
    for title, url in results:
        score = sum(kw.lower() in title.lower() or kw.lower() in url.lower()
                    for kw in keywords)
        scored.append((score, title, url))
    scored.sort(reverse=True)
    return scored[0][2] if scored else None

# ------------------------------------------------------------
# Image scraping (reprend ton code)
# ------------------------------------------------------------
def fetch_image_urls_simple(url, limit=3):
    print("🔍 Essai avec la méthode SIMPLE...")
    try:
        r = requests.get(url, headers=SIMPLE_HEADERS, timeout=15, verify=False)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        urls = []
        for img in soup.find_all("img"):
            u = img.get("src") or img.get("data-src") or img.get("data-original")
            if not u:
                continue
            absu = urljoin(url, u)
            if not re.search(r"-S\.", absu, re.I):
                if re.search(r"\.(jpg|jpeg|png|webp)$", absu, re.I):
                    urls.append(absu)
        urls = list(dict.fromkeys(urls))
        print(f"  ✅ Méthode simple: {len(urls)} images trouvées")
        return urls[:limit]
    except Exception as e:
        print(f"  ❌ Méthode simple échouée: {e}")
        return []

def create_session():
    session = requests.Session()
    session.headers.update(ADVANCED_HEADERS)
    session.cookies.update({'cookieconsent_status': 'dismiss', 'accepted_cookies': 'true'})
    return session

def fetch_image_urls_advanced(url, limit=3, max_retries=3):
    print("🔍 Essai avec la méthode AVANCÉE...")
    session = create_session()
    for attempt in range(max_retries):
        try:
            print(f"  Tentative {attempt + 1}/{max_retries}...")
            if attempt > 0:
                time.sleep(random.uniform(2, 5))
            if attempt == 1:
                try:
                    home_url = f"https://{url.split('/')[2]}/"
                    session.get(home_url, timeout=15)
                    time.sleep(random.uniform(1, 3))
                except:
                    pass
            headers_copy = ADVANCED_HEADERS.copy()
            if attempt > 0:
                headers_copy["Referer"] = f"https://{url.split('/')[2]}/"
            r = session.get(url, headers=headers_copy, timeout=20, verify=False)
            if r.status_code == 403:
                if attempt < max_retries - 1:
                    continue
                else:
                    raise requests.exceptions.HTTPError(f"403 Client Error après {max_retries} tentatives")
            r.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
    soup = BeautifulSoup(r.text, "html.parser")
    urls = []

    script_patterns = [
        r'"imageUrl":\s*"([^"]+)"',
        r'"image":\s*"([^"]+)"',
        r'"src":\s*"([^"]+\.(?:jpg|jpeg|png|webp))"',
        r'imageUrls?["\']\s*:\s*\[([^\]]+)\]',
        r'productImages?["\']\s*:\s*\[([^\]]+)\]',
        r'"url":\s*"([^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'"href":\s*"([^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'https://[^"\s]*\.(?:jpg|jpeg|png|webp)(?:\?[^"\s]*)?',
        r'"media":\s*\{[^}]*"url":\s*"([^"]+)"',
        r'"assets":\s*\[[^\]]*"([^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"'
    ]
    for pattern in script_patterns:
        matches = re.findall(pattern, r.text, re.I)
        for match in matches:
            if isinstance(match, str) and re.search(r'\.(jpg|jpeg|png|webp)', match, re.I):
                clean_url = match.replace('\\/', '/').replace('\\"', '"')
                absu = urljoin(url, clean_url)
                if not re.search(r"-S\.|thumb|mini|small|icon|logo", absu, re.I):
                    urls.append(absu)

    for meta in soup.find_all("meta", property="og:image"):
        if meta.get("content"):
            absu = urljoin(url, meta["content"])
            if re.search(r'\.(jpg|jpeg|png|webp)', absu, re.I):
                urls.append(absu)

    selectors = [
        "img",".product-image img",".gallery img","[data-role='product-image'] img",
        ".product-media img",".product-gallery img",".image-container img",
        "[class*='product'] img","[class*='image'] img"
    ]
    for selector in selectors:
        for img in soup.select(selector):
            for attr in ["src","data-src","data-original","data-lazy","data-zoom-src","data-large","data-full"]:
                u = img.get(attr)
                if u:
                    absu = urljoin(url, u)
                    if re.search(r'\.(jpg|jpeg|png|webp)', absu, re.I):
                        if not re.search(r"-S\.|thumb|mini|small|icon", absu, re.I):
                            urls.append(absu)

    for elem in soup.find_all(attrs={"style": True}):
        style = elem.get("style", "")
        bg_matches = re.findall(r'background-image:\s*url\(["\']?([^"\']+)["\']?\)', style)
        for match in bg_matches:
            if re.search(r'\.(jpg|jpeg|png|webp)', match, re.I):
                absu = urljoin(url, match)
                urls.append(absu)

    urls = list(dict.fromkeys(urls))
    filtered_urls = []
    for u in urls:
        if not re.search(r'logo|icon|favicon|header|footer|nav|menu|banner', u, re.I):
            if re.search(r'\.(jpg|jpeg|png|webp)', u, re.I):
                filtered_urls.append(u)
    return filtered_urls[:limit]

def download_images(urls, out_dir, use_advanced=False):
    os.makedirs(out_dir, exist_ok=True)
    if use_advanced:
        session = create_session()
        headers = ADVANCED_HEADERS.copy()
        headers.update({"Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"})
    else:
        session = requests.Session()
        headers = SIMPLE_HEADERS

    for i, u in enumerate(urls):
        try:
            if use_advanced and i > 0:
                time.sleep(random.uniform(1, 3))
            if use_advanced:
                img_headers = headers.copy()
                img_headers["Referer"] = u.split('/')[0] + '//' + u.split('/')[2] + '/'
            else:
                img_headers = headers
            r = session.get(u, headers=img_headers, timeout=20, verify=False)
            r.raise_for_status()
            filename = f"image{i+1}.jpg"
            path = os.path.join(out_dir, filename)
            with open(path, "wb") as f:
                f.write(r.content)
            print(f"✔ Image sauvegardée: {path} ({len(r.content)} bytes)")
        except Exception as e:
            print(f"✘ Erreur téléchargement: {u} - {e}")

def fetch_and_download(url, out_dir, limit=1):
    print(f"=== TRAITEMENT DE: {url} ===\n")
    urls = fetch_image_urls_simple(url, limit)
    if urls and len(urls) >= 1:
        print(f"\n✅ Méthode SIMPLE réussie !")
        download_images(urls, out_dir, use_advanced=False)
        return
    print("\n⚠️ Méthode simple insuffisante, passage à la méthode AVANCÉE...")
    try:
        urls = fetch_image_urls_advanced(url, limit)
        if not urls:
            print("❌ Aucune image trouvée avec les deux méthodes")
            return
        print(f"\n✅ Méthode AVANCÉE réussie !")
        download_images(urls, out_dir, use_advanced=True)
    except Exception as e:
        print(f"❌ Erreur avec méthode avancée: {e}")

# ------------------------------------------------------------
# Playwright PDF (reprend ton code)
# ------------------------------------------------------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def _get_unique_filepath(directory: Path, filename: str) -> Path:
    base_name, ext = os.path.splitext(filename)
    path = directory / filename
    counter = 1
    while path.exists():
        path = directory / f"{base_name}_{counter}{ext}"
        counter += 1
    return path

# Dictionary to store hashes of downloaded PDFs and their paths within a single request
_downloaded_pdf_info = {}

def _process_and_save_pdf_content(content_bytes: bytes, suggested_filename: str, download_dir: Path, saved: List[str]) -> bool:
    pdf_hash = hashlib.sha256(content_bytes).hexdigest()

    if pdf_hash in _downloaded_pdf_info:
        # File with this content already exists, add its path to saved and skip saving again
        saved.append(str(_downloaded_pdf_info[pdf_hash]))
        return True

    # If not duplicated, generate a unique filename for the new download
    if not suggested_filename.lower().endswith(".pdf"):
        suggested_filename += ".pdf"
    unique_path = _get_unique_filepath(download_dir, suggested_filename)

    unique_path.parent.mkdir(parents=True, exist_ok=True)
    unique_path.write_bytes(content_bytes)
    
    _downloaded_pdf_info[pdf_hash] = unique_path # Store path of the first instance
    saved.append(str(unique_path))
    return True


def _wait_onetrust_gone(page, timeout_ms=4000):
    for sel in ("#onetrust-banner-sdk", "#onetrust-pc-sdk",".onetrust-pc-dark-filter", "#onetrust-consent-sdk"):
        try:
            page.wait_for_selector(sel, state="hidden", timeout=timeout_ms)
        except Exception:
            pass

def click_cookie_consent(page):
    clicked = False
    for sel in ("#onetrust-accept-btn-handler",
                ".ot-sdk-container #onetrust-accept-btn-handler",
                "#accept-recommended-btn-handler",
                ".save-preference-btn-handler",
                "#axeptio_btn_acceptAll", "button#axeptio_btn_acceptAll"):
        try:
            loc = page.locator(sel)
            if loc.is_visible(timeout=800):
                loc.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        for pat in COOKIE_ACCEPT_LABELS:
            for getter in (
                lambda: page.get_by_role("button", name=re.compile(pat, re.I)),
                lambda: page.get_by_role("link",   name=re.compile(pat, re.I)),
                lambda: page.get_by_text(re.compile(pat, re.I)),
            ):
                try:
                    el = getter()
                    if el and el.count() > 0:
                        el.first.click(timeout=1200)
                        clicked = True
                        break
                except Exception:
                    pass
            if clicked:
                break
    _wait_onetrust_gone(page)
    return clicked

def _save_pdf_response_to_dir(resp, download_dir, saved):
    ctype = (resp.headers.get("content-type") or "").lower()
    if "application/pdf" in ctype:
        body = resp.body()
        name = resp.url.split("/")[-1] or "document.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        
        path = _get_unique_filepath(Path(download_dir), name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        saved.append(str(path))
        return True
    return False

def try_click_and_download(page, context, download_dir, labels):
    download_dir = Path(download_dir); download_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for pat in labels:
        for getter in (
            lambda: page.get_by_role("link",   name=re.compile(pat, re.I)),
            lambda: page.get_by_role("button", name=re.compile(pat, re.I)),
            lambda: page.get_by_text(re.compile(pat, re.I)),
        ):
            try:
                locator = getter()
                if not locator or locator.count() == 0:
                    continue
            except Exception:
                continue
            try:
                target = locator.first.locator("xpath=ancestor-or-self::a | ancestor-or-self::button").first
                if not target or target.count() == 0:
                    target = locator.first
            except Exception:
                target = locator.first
            try:
                target.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            try:
                with page.expect_download(timeout=8000) as dl_info:
                    target.click()
                dl = dl_info.value
                dest = _get_unique_filepath(Path(download_dir), dl.suggested_filename)
                dl.save_as(str(dest))
                saved.append(str(dest))
                continue
            except PWTimeout:
                try:
                    with page.expect_response(
                        lambda r: "application/pdf" in (r.headers.get("content-type","").lower()),
                        timeout=6000
                    ) as resp_info:
                        target.click()
                    if _save_pdf_response_to_dir(resp_info.value, download_dir, saved):
                        continue
                except PWTimeout:
                    try:
                        target.click()
                        page.wait_for_url(re.compile(r"\.pdf($|\?)"), timeout=4000)
                        resp = context.request.get(page.url, verify=False) # Add verify=False here as well if needed
                        if resp.ok:
                            name = page.url.split("/")[-1] or "document.pdf"
                            if not name.lower().endswith(".pdf"):
                                name += ".pdf"
                            path = _get_unique_filepath(Path(download_dir), name)
                            path.write_bytes(resp.body())
                            saved.append(str(path))
                    except PWTimeout:
                        pass
            except Exception:
                pass
    return saved

def try_click_and_download_secom(page, context, download_dir):
    saved = []; download_dir = Path(download_dir); download_dir.mkdir(parents=True, exist_ok=True)
    try: click_cookie_consent(page)
    except Exception: pass
    try:
        anchors = page.locator('a[href*="download-pdf"]')
        for i in range(anchors.count()):
            href = anchors.nth(i).get_attribute("href")
            if not href: continue
            abs_url = urljoin(page.url, href)
            resp = context.request.get(abs_url, verify=False)
            if resp.ok and ("application/pdf" in (resp.headers.get("content-type","").lower()) or abs_url.lower().endswith(".pdf")):
                name = abs_url.split("/")[-1] or "document.pdf"
                if not name.lower().endswith(".pdf"): name += ".pdf"
                unique_path = _get_unique_filepath(download_dir, name)
                unique_path.write_bytes(resp.body())
                saved.append(str(unique_path))
    except Exception:
        pass
    if not saved:
        try:
            all_btn = page.get_by_role("button", name=re.compile(r"\btout\s*télécharger\b", re.I))
            if all_btn and all_btn.count() > 0:
                try:
                    with page.expect_download(timeout=8000) as dl_info:
                        all_btn.first.click()
                    dl = dl_info.value
                    dest = _get_unique_filepath(download_dir, dl.suggested_filename)
                    dl.save_as(str(dest))
                    saved.append(str(dest))
                except PWTimeout:
                    with page.expect_response(lambda r: "application/pdf" in (r.headers.get("content-type","").lower()), timeout=6000) as ri:
                        all_btn.first.click()
                    _save_pdf_response_to_dir(ri.value, download_dir, saved)
        except Exception:
            pass
    if not saved:
        saved.extend(try_click_and_download(page, context, download_dir, SE_COM_LABELS))
    if not saved:
        try:
            see_all = page.get_by_role("link", name=re.compile(r"\bvoir\s*tous?\s*les\s*documents\b", re.I))
            if see_all and see_all.count() > 0:
                see_all.first.click(timeout=3000)
        except Exception:
            pass
        if not saved:
            saved.extend(try_click_and_download(page, context, download_dir, SE_COM_LABELS))
    return saved

def try_click_and_download_cedeo(page, context, download_dir):
    saved = []; download_dir = Path(download_dir); download_dir.mkdir(parents=True, exist_ok=True)
    try: click_cookie_consent(page)
    except Exception: pass
    try:
        links = page.locator('a', has_text=re.compile(r"\bsans\s*prix\b", re.I))
        for i in range(links.count()):
            href = links.nth(i).get_attribute("href")
            if not href: continue
            abs_url = urljoin(page.url, href)
            resp = context.request.get(abs_url, verify=False)
            if resp.ok and ("application/pdf" in (resp.headers.get("content-type","").lower()) or abs_url.lower().endswith(".pdf")):
                name = abs_url.split("/")[-1] or "document.pdf"
                if not name.lower().endswith(".pdf"): name += ".pdf"
                unique_path = _get_unique_filepath(download_dir, name)
                unique_path.write_bytes(resp.body())
                saved.append(str(unique_path))
    except Exception:
        pass
    if not saved:
        try:
            target = page.get_by_role("link", name=re.compile(r"\bsans\s*prix\b", re.I))
            if target and target.count() > 0:
                try: target.first.scroll_into_view_if_needed(timeout=1500)
                except Exception: pass
                try:
                    with page.expect_download(timeout=6000) as dl_info:
                        target.first.click()
                    dl = dl_info.value
                    dest = _get_unique_filepath(download_dir, dl.suggested_filename)
                    dl.save_as(str(dest))
                    saved.append(str(dest))
                except PWTimeout:
                    try:
                        with page.expect_response(lambda r: "application/pdf" in (r.headers.get("content-type","").lower()), timeout=6000) as ri:
                            target.first.click()
                        _save_pdf_response_to_dir(ri.value, download_dir, saved)
                    except Exception:
                        pass
        except Exception:
            pass
    if not saved:
        saved.extend(try_click_and_download(page, context, download_dir, CEDEO_LABELS))
    return saved

def try_click_and_download_pointp(page, context, download_dir):
    saved = []; download_dir = Path(download_dir); download_dir.mkdir(parents=True, exist_ok=True)
    try: click_cookie_consent(page)
    except Exception: pass
    try:
        anchors = page.locator('a[href$=".pdf"], a[href*=".pdf?"]')
        for i in range(min(25, anchors.count())):
            href = anchors.nth(i).get_attribute("href")
            if not href: continue
            abs_url = urljoin(page.url, href)
            resp = context.request.get(abs_url, verify=False)
            if resp.ok:
                if "application/pdf" in (resp.headers.get("content-type","").lower()) or abs_url.lower().endswith(".pdf"):
                    name = abs_url.split("/")[-1] or "document.pdf"
                    unique_path = _get_unique_filepath(download_dir, name)
                    unique_path.write_bytes(resp.body())
                    saved.append(str(unique_path))
    except Exception:
        pass
    if not saved:
        try:
            link = page.get_by_role("link", name=re.compile(r"\bsans\s*prix\b", re.I))
            if link and link.count() > 0:
                try: link.first.scroll_into_view_if_needed(timeout=1500)
                except Exception: pass
                try:
                    with page.expect_download(timeout=7000) as dl_info:
                        link.first.click()
                    dl = dl_info.value
                    dest = _get_unique_filepath(download_dir, dl.suggested_filename)
                    dl.save_as(str(dest))
                    saved.append(str(dest))
                except PWTimeout:
                    try:
                        with page.expect_response(lambda r: "application/pdf" in (r.headers.get("content-type","").lower()), timeout=6000) as ri:
                            link.first.click()
                        _save_pdf_response_to_dir(ri.value, download_dir, saved)
                    except Exception:
                        pass
        except Exception:
            pass
    if not saved:
        saved.extend(try_click_and_download(page, context, download_dir, CANDIDATE_LABELS))
    return saved

def download_product_pdfs_sync(url: str, download_dir: str = "downloads", headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.goto(url, wait_until="domcontentloaded", timeout=10000)
        try: click_cookie_consent(page)
        except Exception: pass
        saved = []
        if re.search(r"\bse\.com\b", url):
            try: saved.extend(try_click_and_download_secom(page, context, download_dir))
            except Exception: pass
        elif re.search(r"\bcedeo\.fr\b", url):
            try: saved.extend(try_click_and_download_cedeo(page, context, download_dir))
            except Exception: pass
        elif re.search(r"\bpointp\.fr\b", url):
            try: saved.extend(try_click_and_download_pointp(page, context, download_dir))
            except Exception: pass
        if not saved:
            saved.extend(try_click_and_download(page, context, download_dir, CANDIDATE_LABELS))
        browser.close()
        # Deduplicate paths while preserving order
        return list(dict.fromkeys(saved))

def run_in_thread(func, *args, **kwargs):
    out, err = {}, {}
    def _runner():
        try: out["result"] = func(*args, **kwargs)
        except Exception as e: err["error"] = e
    t = Thread(target=_runner, daemon=True); t.start(); t.join()
    if "error" in err: raise err["error"]
    return out.get("result")

# ------------------------------------------------------------
# LLM Prompt & Factory (identiques)
# ------------------------------------------------------------
PROMPT = PromptTemplate.from_template("""
Tu es un assistant expert en produits BTP.
Tu ne dois pas aller chercher d'informations en ligne, mais uniquement analyser le HTML brut fourni.

Analyse le HTML d'une page produit brute ci-dessous, et retourne les informations au format JSON structuré :

- TITRE
- RÉFÉRENCE
- DESCRIPTION
- AVANTAGES
- UTILISATION
- CARACTÉRISTIQUES TECHNIQUES (clé: valeur)

Voici le HTML brut :
```html
{html}
Merci de retourner uniquement le JSON dans un bloc ```json sans aucune explication autour.
""")

def make_llm():
    return AzureChatOpenAI(
        openai_api_version="2023-05-15",
        azure_endpoint=os.getenv("AZURE_OPENAI_LLM_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
        model=os.getenv("AZURE_OPENAI_LLM_MODEL"),
        api_key=os.getenv("AZURE_OPENAI_LLM_API_KEY"),
        validate_base_url=False,
    )

# ------------------------------------------------------------
# Streamlit-compatible processing function
# ------------------------------------------------------------
def process_techsheet_request(titre_produit: str, marque: str, reference: str, template_path: str, selected_domains: List[str]) -> Dict[str, Any]:
    start_time = time.time()
    req_id = str(uuid.uuid4())
    
    # Use the template_path passed from the frontend (which is already absolute)
    # and derive base_dir from it, assuming 'techsheet' is parent of 'data'
    base_dir = Path(template_path).parent / "data" / req_id
    
    images_dir = base_dir/"fiches_images"
    pdfs_dir = base_dir/"fiches_pdfs"
    out_docx = base_dir/"Fiche_Technique_Filled.docx"

    images_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    output_data = {
        "status": "error",
        "message": "",
        "url_source": None,
        "best_url": None,
        "extracted_data": {},
        "generated_docx": None,
        "downloaded_pdfs": [],
        "image_path": None,
        "execution_time": 0,
        "request_id": req_id
    }

    try:
        if not titre_produit:
            raise ValueError("Le titre/nom du produit est obligatoire.")

        search = " ".join(filter(None, [titre_produit, marque, reference]))
        # Use selected_domains if provided, otherwise default to all domains
        domains_to_search = selected_domains if selected_domains else [
            "pointp.fr", "cedeo.fr", "se.com"
        ]

        print("\n[1/6] Recherche de l'URL produit...")
        results, tried = ddg_product_urls(search, domains_to_search, max_results=10)
        best_url = pick_best_result(results, search.split()) if results and any(is_product_url(url, domains_to_search) for _, url in results) else None
        output_data["tried_endpoints"] = tried

        if not best_url:
            output_data["message"] = "Aucune URL produit trouvée."
            return output_data
        output_data["best_url"] = best_url
        output_data["url_source"] = urllib.parse.urlparse(best_url).netloc
        print(f"  → URL détectée : {best_url}")

        print("\n[2/6] Scraping de la page HTML...")
        response = requests.get(best_url, verify=False, timeout=20)
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        text_only = soup.get_text(separator="\n", strip=True)

        print("\n[3/6] Extraction LLM (Azure OpenAI via LangChain)...")
        llm = make_llm()
        chain = LLMChain(llm=llm, prompt=PROMPT)
        llm_response = chain.run(html=text_only)
        print("llm_response:", llm_response)

        match = re.search(r"```json\n(.*?)```", llm_response, re.DOTALL)
        if not match:
            output_data["message"] = f"Aucun bloc JSON trouvé dans la réponse LLM. Réponse brute: {llm_response}"
            return output_data

        data = json.loads(match.group(1))

        # Ensure UTILISATION is always a list of strings
        utilisation_data = data.get("UTILISATION")
        if isinstance(utilisation_data, str):
            utilisation_data = [utilisation_data]
        elif utilisation_data is None:
            utilisation_data = []

        output_data["extracted_data"] = {
            "TITRE": data.get("TITRE"),
            "REFERENCE": data.get("RÉFÉRENCE"),
            "DESCRIPTION": data.get("DESCRIPTION"),
            "AVANTAGES": data.get("AVANTAGES") or [],
            "UTILISATION": utilisation_data,
            "CARACTERISTIQUES TECHNIQUES": data.get("CARACTÉRISTIQUES TECHNIQUES", {}) or {}
        }

        print("\n[4/6] Récupération image produit...")
        fetch_and_download(best_url, str(images_dir), limit=1)
        image1_path = images_dir/"image1.jpg"
        has_image = image1_path.exists()
        if has_image:
            output_data["image_path"] = image1_path.as_posix()

        print("\n[5/6] Génération DOCX (docxtpl) ...")
        if not Path(template_path).exists():
            output_data["message"] = f"Modèle DOCX introuvable : {template_path}"
            return output_data

    # Ensure 'CARACTERISTIQUES TECHNIQUES' is a dictionary, even if missing from LLM response
        caracteristiques_to_process = output_data["extracted_data"].get("CARACTERISTIQUES TECHNIQUES", {})
        caracteristiques_list = [{"titre": k, "valeur": v} for k, v in caracteristiques_to_process.items()]
        caracteristiques_grouped = []
        for i in range(0, len(caracteristiques_list), 2):
            item1 = caracteristiques_list[i]
            item2 = caracteristiques_list[i+1] if i+1 < len(caracteristiques_list) else {"titre": "", "valeur": ""}
            caracteristiques_grouped.append({"item1": item1, "item2": item2})

        doc = DocxTemplate(str(template_path))
        context = {
            "TITRE": output_data["extracted_data"]["TITRE"] or "",
            "REFERENCE": output_data["extracted_data"]["REFERENCE"] or "",
            "DESCRIPTION": output_data["extracted_data"]["DESCRIPTION"] or "",
            "AVANTAGES": "\n".join(output_data["extracted_data"]["AVANTAGES"]) if output_data["extracted_data"]["AVANTAGES"] else "",
            "UTILISATION": output_data["extracted_data"]["UTILISATION"] or "",
            "IMAGE": InlineImage(doc, str(image1_path), width=Cm(3)) if has_image else None,
            "CARACTERISTIQUES": caracteristiques_grouped,
            "DATE": datetime.date.today().strftime("%d/%m/%Y"),
        }
        doc.render(context)
        doc.save(str(out_docx))
        output_data["generated_docx"] = out_docx.as_posix()

        print("\n[6/6] Téléchargement des PDF originaux (Playwright) ...")
        try:
            pdf_saved = run_in_thread(download_product_pdfs_sync, best_url, download_dir=str(pdfs_dir), headless=True)
            output_data["downloaded_pdfs"] = [p for p in pdf_saved]
        except Exception as e:
            print(f"⚠️ Erreur Playwright: {e}")
            output_data["message"] += f" Erreur lors du téléchargement des PDFs: {e}"

        output_data["status"] = "success"
        output_data["message"] = "Fiche technique générée avec succès."

    except Exception as e:
        output_data["message"] = f"Une erreur inattendue est survenue: {e}"
        import traceback
        print(traceback.format_exc())

    finally:
        output_data["execution_time"] = time.time() - start_time
        return output_data

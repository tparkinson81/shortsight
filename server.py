"""
ShortSight — API Server
FastAPI backend for the short thesis scanner dashboard.
"""

import os
import json
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware


# ── API Keys ──
NEWS_KEY = os.getenv("NEWS_API_KEY", "")
FMP_KEY = os.getenv("FMP_API_KEY", "")
UW_KEY = os.getenv("UNUSUAL_WHALES_API_KEY", "")
QUIVER_KEY = os.getenv("QUIVER_API_KEY", "")
APININJAS_KEY = os.getenv("APININJAS_KEY", "")


# ── FastAPI App ──
app = FastAPI(title="ShortSight", description="News & sentiment-driven short scanner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Watchlist ──
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "data", "watchlist.json")

def get_watchlist() -> List[str]:
    os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_watchlist(tickers: List[str]):
    os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(tickers, f)


# ── Background Scanner ──
class BackgroundScanner:
    def __init__(self):
        self.scanner = None
        self.is_running = False
        self.last_scan_time: Optional[str] = None
        self.scan_count = 0
        self.errors: List[str] = []
    
    def initialize(self):
        if not NEWS_KEY or not FMP_KEY:
            self.errors.append("Missing API keys. Set NEWS_API_KEY and FMP_API_KEY.")
            return False
        
        try:
            from engine.scanner import ShortScanner
            self.scanner = ShortScanner(NEWS_KEY, FMP_KEY, UW_KEY, QUIVER_KEY, APININJAS_KEY)
            print("  Scanner module loaded successfully")
            return True
        except Exception as e:
            self.errors.append(f"Scanner init failed: {str(e)}")
            print(f"  Scanner init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def run_scan(self):
        if not self.scanner:
            if not self.initialize():
                return
        
        try:
            self.is_running = True
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.scanner.run_scan)
            self.last_scan_time = datetime.utcnow().isoformat()
            self.scan_count += 1
            self.is_running = False
        except Exception as e:
            self.is_running = False
            self.errors.append(f"Scan error: {str(e)}")
            print(f"[Scanner] Error: {e}")
    
    async def scan_ticker(self, ticker: str) -> Optional[Dict]:
        if not self.scanner:
            if not self.initialize():
                return None
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.scanner.scan_ticker, ticker)
        return result


bg = BackgroundScanner()


# ── Startup ──
@app.on_event("startup")
async def startup():
    print(f"\n  ShortSight starting...")
    print(f"  NEWS_API_KEY: {'✓' if NEWS_KEY else '✗'}")
    print(f"  FMP_API_KEY: {'✓' if FMP_KEY else '✗'}")
    print(f"  UNUSUAL_WHALES: {'✓' if UW_KEY else '○ optional'}")
    print(f"  QUIVER: {'✓' if QUIVER_KEY else '○ optional'}")
    
    if NEWS_KEY and FMP_KEY:
        bg.initialize()
        print(f"  Scanner initialized.")
        # Auto-run first scan
        asyncio.create_task(bg.run_scan())
        print(f"  Auto-scan started...")
    else:
        print(f"  ⚠ Missing API keys — scanner disabled.")


# ════════════════════════════════════════════
# API ENDPOINTS
# ════════════════════════════════════════════

@app.get("/api/health")
async def health():
    ak = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "status": "ok",
        "scanner_ready": bg.scanner is not None,
        "is_scanning": bg.is_running,
        "last_scan": bg.last_scan_time,
        "scan_count": bg.scan_count,
        "errors": bg.errors[-3:] if bg.errors else [],
        "anthropic_key": (ak[:10] + "...") if ak else "MISSING",
    }


# ── Scanner ──

@app.get("/api/scan")
async def get_scan_results():
    """Get most recent scan results."""
    if bg.scanner:
        return bg.scanner.get_cached()
    return {"candidates": [], "found": 0, "scanned_at": None}


@app.post("/api/scan")
async def trigger_scan():
    """Trigger a new full scan."""
    if bg.is_running:
        return {"message": "Scan already in progress. Please wait."}
    
    asyncio.create_task(bg.run_scan())
    return {"message": "Scan started. Screening S&P 500 — this may take a few minutes."}


@app.get("/api/scan/{ticker}")
async def scan_single_ticker(ticker: str):
    """Deep scan a single ticker."""
    ticker = ticker.upper().strip()
    result = await bg.scan_ticker(ticker)
    if result:
        return result
    return {"error": f"Could not analyze {ticker} — no data available or score below threshold."}


# ── Deep Research ──

RESEARCH_TEMPLATE = {
    "Business": ["Company Name", "Ticker", "Description", "Industry", "Market Capitalization", "Fully Diluted Shares", "Short Interest", "Total Debt", "EBITDA", "Adj. Free Cash Flow", "Origin of Idea"],
    "10K and Financials": ["History", "Accounting Policy (Changes)", "Revenue Recognition", "Business", "Undervalued Property", "Unions", "Litigation", "Management Contracts", "Competitive Position", "Risk Disclosure", "Atypical Line Items", "Off Balance Sheet Liabilities (SPV, Contingency, Operating Leases, Guarantees)", "Debt Schedule", "Valuation Allowance", "NOLs", "Inventories (FIFO/LIFO)", "Tax Rate", "Depreciation Expense / Gross PPE", "Operating Cash Flow / Net Income", "Margins Rising / Falling", "Cap Ex Rising / Falling", "Liquidity", "Other Comprehensive Income / Shareholder Equity", "Options Use"],
    "Competitive Advantage": ["Summary", "Company Age", "Industry Age", "ROE (Rising / Falling)", "Pre-Tax Margin (Rising / Falling)", "Gross Margin (Rising / Falling)", "Technology Threat", "Market Share (Rising / Falling)", "Strategy"],
    "Pension and OPEB": ["Pension Deficit / Excess", "Discount Rate", "Expected Return", "Total Added Liability"],
    "10Q": ["Covenants", "Events since Quarter-end", "Inventory Bloat", "DSO Bloat", "Deferred Revenue Comparable", "Litigation Update", "Reported Shares Outstanding"],
    "Corporate Governance": ["Proxy Filing Deadline", "Related Party Transactions", "Compensation", "Number of Directors", "Classified", "Term", "Management Bonus Tied to", "Employee Directors", "Poison Pill", "Golden Parachutes", "Change of Control", "Standstill Agreement", "State of Incorporation", "Share Classes (Dual / Supervoting)", "Management Control via Share Ownership", "Founding Family", "Previous LBO, MBO", "Previous Takeover Defense", "Current Involvement of Investment Firm"],
    "8K": ["Auditor Comments", "Offering Documents", "Disclosure Statement", "Shelf Registration", "Secondary Purchase Offering", "IPO Filing Date"],
    "News": ["X", "Reddit", "Substack", "Seeking Alpha"],
    "Comps": ["Public Comps", "Private Comps", "Buyout Comps", "Previous Bids"],
    "Insider Trading": ["Overall", "Automatic Selling", "Trend"],
    "Earnings Call": ["Date", "Attendees", "Commentary", "Q&A"],
    "Investigative Journalism": ["Glassdoor Reviews", "Data Search", "FOIA"],
    "Valuation": ["Value Range", "Current Price", "Discount", "Annual Sales", "MVE / FCF", "EV / EBITDA", "Historical ROI", "Industry Growth Rate"],
    "Timeline and Catalysts": ["Potential Catalysts"],
    "Conclusion": ["Management Quality", "Competitive Position", "Activism", "Public Control", "Downside", "Overall"],
}


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    """Call Anthropic API with web search."""
    import urllib.request
    
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "[ERROR: ANTHROPIC_API_KEY not set in environment variables]"
    
    print(f"  [Anthropic] Key prefix: {api_key[:12]}... length={len(api_key)}")
    
    payload = json.dumps({
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 16000,
        "system": system_prompt,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        "messages": [{"role": "user", "content": user_prompt}]
    }).encode()
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            text_parts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
            return "\n".join(text_parts) if text_parts else "[No response]"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except:
            pass
        print(f"  [Anthropic] HTTP {e.code}: {body}")
        return f"[API Error: HTTP Error {e.code}: {e.reason}. {body}]"
    except Exception as e:
        return f"[API Error: {str(e)[:200]}]"


def _research_section(ticker: str, company_name: str, section: str, fields: list) -> Dict:
    """Research one section of the template."""
    fields_list = "\n".join(f"- {f}" for f in fields)
    
    system = f"""You are a professional short-selling research analyst conducting deep due diligence on {ticker} ({company_name}). 
You must research and fill out each field with specific, factual data. Use web search to find current, accurate information.
Be concise but thorough. Include specific numbers, dates, and facts where possible.
If information is genuinely unavailable, say "Not found" — never fabricate data.

CRITICAL: Respond ONLY with valid JSON. No markdown, no backticks, no preamble. 
The JSON should be an object where each key is the field name and the value is your research finding as a string."""

    user = f"""Research the following fields for {ticker} ({company_name}) under the "{section}" category:

{fields_list}

Respond with a JSON object mapping each field name to your finding. Example format:
{{"Field Name": "Your detailed finding here", "Another Field": "Finding"}}"""

    raw = _call_anthropic(system, user)
    
    # Parse JSON from response
    try:
        # Strip any markdown fencing
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        if clean.startswith("json"):
            clean = clean[4:].strip()
        result = json.loads(clean)
        return result
    except json.JSONDecodeError:
        # Return raw text mapped to first field
        return {fields[0]: raw, **{f: "[Parse error — see first field]" for f in fields[1:]}}


@app.get("/api/research/template")
async def get_research_template():
    """Return the research template structure."""
    return {"sections": RESEARCH_TEMPLATE}


@app.get("/api/research/{ticker}")
async def run_research(ticker: str):
    """Run deep research on a ticker, filling out all template sections."""
    ticker = ticker.upper().strip()
    
    # Check for Anthropic API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        return {"error": "ANTHROPIC_API_KEY not set. Add it to Railway environment variables."}
    
    # Get company name from FMP
    company_name = ticker
    if bg.scanner:
        try:
            profile = bg.scanner.fmp.get_profile(ticker)
            company_name = profile.get("companyName", ticker)
        except:
            pass
    
    print(f"\n  [Research] Starting deep research on {ticker} ({company_name})...")
    
    # Research each section
    loop = asyncio.get_event_loop()
    results = {}
    section_list = list(RESEARCH_TEMPLATE.items())
    
    for section_name, fields in section_list:
        print(f"  [Research] Researching: {section_name} ({len(fields)} fields)")
        try:
            section_data = await loop.run_in_executor(
                None, _research_section, ticker, company_name, section_name, fields
            )
            results[section_name] = section_data
        except Exception as e:
            print(f"  [Research] Error in {section_name}: {e}")
            results[section_name] = {f: f"[Error: {str(e)[:100]}]" for f in fields}
    
    print(f"  [Research] Complete — {len(results)} sections filled")
    
    return {
        "ticker": ticker,
        "company_name": company_name,
        "researched_at": datetime.utcnow().isoformat(),
        "sections": results
    }


# ── Watchlist ──

@app.get("/api/watchlist")
async def get_watchlist_api():
    return {"tickers": get_watchlist()}


@app.post("/api/watchlist/add/{ticker}")
async def add_to_watchlist(ticker: str):
    ticker = ticker.upper().strip()
    wl = get_watchlist()
    if ticker in wl:
        return {"message": f"{ticker} already in watchlist.", "tickers": wl}
    if len(wl) >= 30:
        raise HTTPException(status_code=400, detail="Watchlist full (30 max).")
    wl.append(ticker)
    save_watchlist(wl)
    return {"message": f"Added {ticker}.", "tickers": wl}


@app.post("/api/watchlist/remove/{ticker}")
async def remove_from_watchlist(ticker: str):
    ticker = ticker.upper().strip()
    wl = get_watchlist()
    if ticker in wl:
        wl.remove(ticker)
        save_watchlist(wl)
        return {"message": f"Removed {ticker}.", "tickers": wl}
    return {"message": f"{ticker} not in watchlist.", "tickers": wl}


# ── News Feed ──

@app.get("/api/news/{ticker}")
async def get_ticker_news(ticker: str):
    """Get news for a specific ticker with sentiment scores."""
    if not bg.scanner:
        if not bg.initialize():
            return {"articles": [], "error": "Scanner not initialized"}
    
    ticker = ticker.upper().strip()
    articles = []
    
    try:
        articles = bg.scanner.news.get_ticker_news(ticker, days=7)
    except Exception:
        pass
    
    try:
        fmp_news = bg.scanner.fmp.get_stock_news(ticker)
        for item in (fmp_news or []):
            articles.append({
                "title": item.get("title", ""),
                "description": item.get("text", ""),
                "source": {"name": item.get("site", "")},
                "url": item.get("url", ""),
                "publishedAt": item.get("publishedDate", "")
            })
    except Exception:
        pass
    
    scored = bg.scanner.sentiment.score_headlines(articles, ticker)
    return scored


@app.get("/api/news")
async def get_market_news():
    """Get bearish market news feed."""
    if not bg.scanner:
        if not bg.initialize():
            print("[News] Scanner not initialized")
            return {"articles": []}
    
    articles = []
    
    # Primary: FMP general news
    try:
        print("[News] Fetching FMP general news...")
        fmp_news = bg.scanner.fmp.get_general_news(limit=50)
        print(f"[News] FMP raw type: {type(fmp_news)}, len: {len(fmp_news) if isinstance(fmp_news, list) else 'N/A'}")
        for item in (fmp_news or []):
            articles.append({
                "title": item.get("title", ""),
                "description": item.get("text", ""),
                "source": {"name": item.get("site", item.get("source", ""))},
                "url": item.get("url", ""),
                "publishedAt": item.get("publishedDate", item.get("date", ""))
            })
        print(f"[News] FMP returned {len(articles)} articles")
    except Exception as e:
        import traceback
        print(f"[News] FMP error: {e}")
        traceback.print_exc()
    
    # Fallback: FMP stock-specific news for major tickers
    if not articles:
        print("[News] Trying FMP stock-specific news fallback...")
        for ticker in ["AAPL", "TSLA", "NVDA", "MSFT", "META", "AMZN", "GOOGL"]:
            try:
                news = bg.scanner.fmp.get_stock_news(ticker)
                for item in (news or [])[:5]:
                    articles.append({
                        "title": item.get("title", ""),
                        "description": item.get("text", ""),
                        "source": {"name": item.get("site", item.get("source", ""))},
                        "url": item.get("url", ""),
                        "publishedAt": item.get("publishedDate", item.get("date", ""))
                    })
            except Exception:
                pass
        print(f"[News] FMP stock fallback returned {len(articles)} articles")
    
    # Final fallback: NewsAPI
    if not articles:
        try:
            print("[News] Trying NewsAPI fallback...")
            newsapi_articles = bg.scanner.news.get_market_news(
                query="stock decline OR earnings miss OR layoffs OR downgrade",
                days=2
            )
            articles = newsapi_articles
            print(f"[News] NewsAPI returned {len(articles)} articles")
        except Exception as e:
            print(f"[News] NewsAPI error: {e}")
    
    if not articles:
        print("[News] All sources returned 0 articles")
        return {"articles": []}
    
    # Deduplicate by title
    seen = set()
    unique = []
    for a in articles:
        t = a.get("title", "")
        if t and t not in seen:
            seen.add(t)
            unique.append(a)
    
    scored = bg.scanner.sentiment.score_headlines(unique)
    return scored


@app.get("/api/dashboard")
async def dashboard():
    """All data for the dashboard in one call."""
    scan = bg.scanner.get_cached() if bg.scanner else {"candidates": [], "scanned_at": None}
    
    return {
        "scan": scan,
        "watchlist": get_watchlist(),
        "status": {
            "scanner_ready": bg.scanner is not None,
            "is_scanning": bg.is_running,
            "last_scan": bg.last_scan_time,
            "scan_count": bg.scan_count,
        }
    }


# ════════════════════════════════════════════
# STATIC FILES & DASHBOARD
# ════════════════════════════════════════════

@app.get("/api/diagnose")
async def diagnose():
    """Test every FMP endpoint path variant and report what works."""
    import urllib.request as ureq, urllib.parse as uparse
    base = "https://financialmodelingprep.com/stable"
    key = FMP_KEY
    results = {}
    tests = {
        # Known working
        "profile": f"{base}/profile?symbol=AAPL&apikey={key}",
        "sp500-constituent": f"{base}/sp500-constituent?apikey={key}",
        "income-statement": f"{base}/income-statement?symbol=AAPL&period=quarter&limit=2&apikey={key}",
        "key-metrics": f"{base}/key-metrics?symbol=AAPL&period=ttm&apikey={key}",
        "shares-float": f"{base}/shares-float?symbol=AAPL&apikey={key}",
        "news_stock_latest": f"{base}/news/stock-latest?symbol=AAPL&limit=5&apikey={key}",
        "price-target-consensus": f"{base}/price-target-consensus?symbol=AAPL&apikey={key}",
        # Earnings surprises variants
        "earnings-surprises": f"{base}/earnings-surprises?symbol=AAPL&apikey={key}",
        "earnings-surprise": f"{base}/earnings-surprise?symbol=AAPL&apikey={key}",
        # Insider trading variants
        "insider-trading": f"{base}/insider-trading?symbol=AAPL&limit=5&apikey={key}",
        "insider-trading/latest": f"{base}/insider-trading/latest?symbol=AAPL&limit=5&apikey={key}",
        "insider-trade": f"{base}/insider-trade?symbol=AAPL&limit=5&apikey={key}",
        # Analyst estimates variants
        "analyst-estimates_bare": f"{base}/analyst-estimates?symbol=AAPL&limit=1&apikey={key}",
        "analyst-estimates_full": f"{base}/analyst-estimates?symbol=AAPL&period=annual&page=0&limit=1&apikey={key}",
        # Analyst recommendations variants
        "analyst-recommendations": f"{base}/analyst-recommendations?symbol=AAPL&apikey={key}",
        "analyst-stock-recommendations": f"{base}/analyst-stock-recommendations?symbol=AAPL&apikey={key}",
        "recommendations": f"{base}/recommendations?symbol=AAPL&apikey={key}",
        # Grades variants
        "stock-grade": f"{base}/stock-grade?symbol=AAPL&limit=3&apikey={key}",
        "grades": f"{base}/grades?symbol=AAPL&limit=3&apikey={key}",
        "grades-summary": f"{base}/grades-summary?symbol=AAPL&apikey={key}",
        # Transcript variants
        "transcript_dates_v1": f"{base}/earning-call-transcript-available-dates?symbol=AAPL&apikey={key}",
        "transcript_dates_v2": f"{base}/earnings-transcript-list?symbol=AAPL&apikey={key}",
        "transcript_v1": f"{base}/earning-call-transcript?symbol=AAPL&year=2024&quarter=4&apikey={key}",
        "transcript_v2": f"{base}/earnings-transcript?symbol=AAPL&year=2024&quarter=4&apikey={key}",
        # Congressional trading variants
        "senate-trading-rss": f"{base}/senate-trading-rss-feed?limit=5&apikey={key}",
        "senate-trading": f"{base}/senate-trading?limit=5&apikey={key}",
        "senate-disclosure": f"{base}/senate-disclosure?limit=5&apikey={key}",
        "senate-trade": f"{base}/senate-trade?limit=5&apikey={key}",
        "house-disclosure-rss": f"{base}/house-disclosure-rss-feed?limit=5&apikey={key}",
        "house-disclosure": f"{base}/house-disclosure?limit=5&apikey={key}",
        "house-trade": f"{base}/house-trade?limit=5&apikey={key}",
        # Ratings
        "ratings-snapshot": f"{base}/ratings-snapshot?symbol=AAPL&apikey={key}",
    }
    for name, url in tests.items():
        try:
            req = ureq.Request(url, headers={"User-Agent": "ShortSight/1.0"})
            with ureq.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
                if isinstance(data, list):
                    results[name] = {"ok": True, "count": len(data), "keys": list(data[0].keys())[:8] if data and isinstance(data[0], dict) else []}
                elif isinstance(data, dict):
                    err = data.get("Error Message", data.get("error", ""))
                    if err:
                        results[name] = {"ok": False, "error": str(err)[:150]}
                    else:
                        results[name] = {"ok": True, "keys": list(data.keys())[:8]}
                else:
                    results[name] = {"ok": True, "type": str(type(data))}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:150]}
    
    # API Ninjas test (if key is set)
    ninjas_key = os.environ.get("APININJAS_KEY", "")
    if ninjas_key:
        try:
            url = f"https://api.api-ninjas.com/v1/earningstranscriptsearch?ticker=AAPL"
            req = ureq.Request(url, headers={"X-Api-Key": ninjas_key, "Accept": "application/json"})
            with ureq.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                results["apininjas_transcripts"] = {"ok": True, "count": len(data) if isinstance(data, list) else 1}
        except Exception as e:
            results["apininjas_transcripts"] = {"ok": False, "error": str(e)[:150]}
    
    return {"fmp_key_set": bool(FMP_KEY), "fmp_key_prefix": (FMP_KEY[:8] + "...") if FMP_KEY else "MISSING", "tests": results}


@app.get("/api/quicktest")
async def quicktest():
    """Scan 5 tickers and return raw scores — for debugging pipeline."""
    if not bg.scanner:
        bg.initialize()
    if not bg.scanner:
        return {"error": "Scanner not initialized", "keys": {"news": bool(NEWS_KEY), "fmp": bool(FMP_KEY)}}
    
    # First test raw FMP connectivity
    fmp_test = {}
    try:
        profile = bg.scanner.fmp.get_profile("TSLA")
        fmp_test["profile"] = {"ok": bool(profile.get("price")), "price": profile.get("price"), "name": profile.get("companyName"), "range": profile.get("range")}
    except Exception as e:
        fmp_test["profile"] = {"ok": False, "error": str(e)}
    try:
        metrics = bg.scanner.fmp.get_key_metrics("TSLA")
        fmp_test["key_metrics"] = {"ok": bool(metrics), "parsed": metrics}
        # Also get raw response to see actual field names
        raw_km = bg.scanner.fmp._get("key-metrics", {"symbol": "TSLA", "period": "ttm"})
        if isinstance(raw_km, list) and raw_km:
            fmp_test["key_metrics_raw_keys"] = list(raw_km[0].keys())[:20]
            fmp_test["key_metrics_raw_sample"] = {k: raw_km[0][k] for k in list(raw_km[0].keys())[:15]}
        elif isinstance(raw_km, list):
            fmp_test["key_metrics_raw"] = "empty list"
            # Try without period param
            raw_km2 = bg.scanner.fmp._get("key-metrics", {"symbol": "TSLA"})
            if isinstance(raw_km2, list) and raw_km2:
                fmp_test["key_metrics_no_period_keys"] = list(raw_km2[0].keys())[:20]
                fmp_test["key_metrics_no_period_sample"] = {k: raw_km2[0][k] for k in list(raw_km2[0].keys())[:15]}
    except Exception as e:
        fmp_test["key_metrics"] = {"ok": False, "error": str(e)}
    try:
        sp = bg.scanner.fmp.get_sp500_constituents()
        fmp_test["sp500"] = {"ok": bool(sp), "count": len(sp)}
    except Exception as e:
        fmp_test["sp500"] = {"ok": False, "error": str(e)}
    
    # Short interest check
    try:
        sf_raw = bg.scanner.fmp._get("shares-float", {"symbol": "TSLA"})
        if isinstance(sf_raw, list) and sf_raw:
            fmp_test["shares_float_keys"] = list(sf_raw[0].keys())[:15]
            fmp_test["shares_float_sample"] = {k: sf_raw[0][k] for k in list(sf_raw[0].keys())[:10]}
        else:
            fmp_test["shares_float"] = {"ok": False, "data": str(sf_raw)[:200]}
    except Exception as e:
        fmp_test["shares_float"] = {"ok": False, "error": str(e)}
    
    # Batch profile check — this is what _quick_screen uses
    try:
        # Raw FMP response first (unparsed)
        raw_profiles = bg.scanner.fmp._get("profile", {"symbol": "TSLA,AAPL"})
        if isinstance(raw_profiles, list) and raw_profiles:
            fmp_test["raw_profile_keys"] = list(raw_profiles[0].keys())
            fmp_test["raw_profile_sample"] = {k: raw_profiles[0].get(k) for k in ["symbol","pe","changes","mktCap","price","changesPercentage","marketCap","change","changePercentage","companyName"] if raw_profiles[0].get(k) is not None}
        # Parsed batch profiles
        batch_raw = bg.scanner.fmp.get_batch_profiles(["TSLA", "AAPL", "NVDA"])
        if isinstance(batch_raw, list) and batch_raw:
            fmp_test["batch_profile_count"] = len(batch_raw)
            fmp_test["batch_profile_keys"] = list(batch_raw[0].keys())[:20]
            fmp_test["batch_profile_sample"] = {k: batch_raw[0].get(k) for k in ["symbol", "pe", "changes", "mktCap", "price", "changesPercentage", "companyName"]}
        else:
            fmp_test["batch_profile"] = {"ok": False, "data": str(batch_raw)[:300]}
    except Exception as e:
        fmp_test["batch_profile"] = {"ok": False, "error": str(e)}
    
    # Then scan tickers
    test_tickers = ["TSLA", "NVDA", "NKE", "INTC", "BA"]
    results = []
    loop = asyncio.get_event_loop()
    for t in test_tickers:
        try:
            r = await loop.run_in_executor(None, bg.scanner.scan_ticker, t)
            if r:
                results.append({"ticker": t, "total_score": r["total_score"], "conviction": r["conviction"],
                                "scores": r["scores"], "critical": r["critical_count"], "elevated": r["elevated_count"]})
            else:
                results.append({"ticker": t, "total_score": 0, "conviction": "filtered", "scores": {}, "note": "scan_ticker returned None"})
        except Exception as e:
            results.append({"ticker": t, "error": str(e), "traceback": __import__('traceback').format_exc()})
    return {"fmp_connectivity": fmp_test, "test_results": results}


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return JSONResponse({
        "message": "ShortSight API running. Dashboard not found.",
        "docs": "/docs",
        "health": "/api/health"
    })

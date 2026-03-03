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
            self.scanner = ShortScanner(NEWS_KEY, FMP_KEY, UW_KEY, QUIVER_KEY)
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
    else:
        print(f"  ⚠ Missing API keys — scanner disabled.")


# ════════════════════════════════════════════
# API ENDPOINTS
# ════════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "scanner_ready": bg.scanner is not None,
        "is_scanning": bg.is_running,
        "last_scan": bg.last_scan_time,
        "scan_count": bg.scan_count,
        "errors": bg.errors[-3:] if bg.errors else []
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
    """Test every FMP endpoint and report what works."""
    import urllib.request as ureq, urllib.parse as uparse
    base = "https://financialmodelingprep.com/stable"
    key = FMP_KEY
    results = {}
    tests = {
        "profile": f"{base}/profile?symbol=AAPL&apikey={key}",
        "sp500-constituent": f"{base}/sp500-constituent?apikey={key}",
        "income-statement": f"{base}/income-statement?symbol=AAPL&period=quarter&limit=2&apikey={key}",
        "earnings-surprises": f"{base}/earnings-surprises?symbol=AAPL&apikey={key}",
        "insider-trading": f"{base}/insider-trading?symbol=AAPL&limit=5&apikey={key}",
        "analyst-estimates": f"{base}/analyst-estimates?symbol=AAPL&limit=1&apikey={key}",
        "analyst-recommendations": f"{base}/analyst-recommendations?symbol=AAPL&apikey={key}",
        "stock-grade": f"{base}/stock-grade?symbol=AAPL&limit=3&apikey={key}",
        "key-metrics": f"{base}/key-metrics?symbol=AAPL&period=ttm&apikey={key}",
        "shares-float": f"{base}/shares-float?symbol=AAPL&apikey={key}",
        "news_stock_latest": f"{base}/news/stock-latest?symbol=AAPL&limit=5&apikey={key}",
        "stock_news_old": f"{base}/stock-news?symbol=AAPL&limit=5&apikey={key}",
        "transcript_dates": f"{base}/earning-call-transcript-available-dates?symbol=AAPL&apikey={key}",
        "senate_rss": f"{base}/senate-trading-rss-feed?apikey={key}",
        "senate_trading": f"{base}/senate-trading?apikey={key}",
        "house_rss": f"{base}/house-disclosure-rss-feed?apikey={key}",
        "price-target-consensus": f"{base}/price-target-consensus?symbol=AAPL&apikey={key}",
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
    return {"fmp_key_set": bool(FMP_KEY), "fmp_key_prefix": (FMP_KEY[:8] + "...") if FMP_KEY else "MISSING", "tests": results}


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

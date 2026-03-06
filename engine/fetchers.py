"""
ShortSight — Data Fetchers
Fetches data from NewsAPI, FMP (stable), Reddit, and SEC EDGAR.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, List, Optional
from datetime import datetime, timedelta


# ═══════════════════════════════════════════
# NEWS API FETCHER
# ═══════════════════════════════════════════

class NewsFetcher:
    """Fetches news from NewsAPI.org."""
    
    BASE_URL = "https://newsapi.org/v2"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def _get(self, endpoint: str, params: Dict) -> Dict:
        params["apiKey"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ShortSight/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[NewsAPI] Error: {e}")
            return {}
    
    def get_ticker_news(self, ticker: str, company_name: str = "", days: int = 7) -> List[Dict]:
        """Get news for a specific ticker."""
        query = ticker
        if company_name:
            query = f'"{company_name}" OR {ticker}'
        
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        data = self._get("everything", {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": "50"
        })
        return data.get("articles", [])
    
    def get_market_news(self, query: str = "stock market", days: int = 1) -> List[Dict]:
        """Get general market news."""
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._get("everything", {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": "100"
        })
        return data.get("articles", [])


# ═══════════════════════════════════════════
# FMP FETCHER (STABLE API)
# ═══════════════════════════════════════════

class FMPFetcher:
    """Fetches financial data from FMP stable API."""
    
    BASE_URL = "https://financialmodelingprep.com/stable"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def _get(self, endpoint: str, params: Dict = None) -> any:
        if params is None:
            params = {}
        params["apikey"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ShortSight/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.request.HTTPError as e:
            if e.code == 429:
                print(f"[FMP] RATE LIMITED on {endpoint} — waiting 10s")
                import time; time.sleep(10)
                # Retry once
                try:
                    req2 = urllib.request.Request(url, headers={"User-Agent": "ShortSight/1.0"})
                    with urllib.request.urlopen(req2, timeout=15) as resp2:
                        return json.loads(resp2.read().decode())
                except:
                    pass
            print(f"[FMP] HTTP {e.code} on {endpoint}")
            return []
        except Exception as e:
            print(f"[FMP] Error {endpoint}: {e}")
            return []
    
    def get_stock_screener(self, market_cap_min: int = 500000000, limit: int = 500) -> List[Dict]:
        """Use FMP screener to get bulk stock data in one call."""
        data = self._get("stock-screener", {
            "marketCapMoreThan": str(market_cap_min),
            "isActivelyTrading": "true",
            "limit": str(limit),
            "exchange": "NYSE,NASDAQ"
        })
        if isinstance(data, list):
            return data
        return []
    
    def get_profile(self, ticker: str) -> Dict:
        data = self._get("profile", {"symbol": ticker})
        if isinstance(data, list) and data:
            p = data[0]
            return {
                "companyName": p.get("companyName", ticker),
                "sector": p.get("sector", ""),
                "industry": p.get("industry", ""),
                "mktCap": p.get("mktCap", 0),
                "price": p.get("price", 0),
                "beta": p.get("beta", 1.0),
                "pe": p.get("pe", 0),
                "changes": p.get("changes", 0),
                "changesPercentage": p.get("changesPercentage", 0),
                "range": p.get("range", ""),  # "52wLow-52wHigh"
            }
        return {"companyName": ticker}
    
    def get_batch_profiles(self, tickers: List[str]) -> List[Dict]:
        """Get profiles for multiple tickers in one call, parsed consistently."""
        tickers_str = ",".join(tickers)
        data = self._get("profile", {"symbol": tickers_str})
        if isinstance(data, list):
            results = []
            for p in data:
                results.append({
                    "symbol": p.get("symbol", ""),
                    "companyName": p.get("companyName", ""),
                    "sector": p.get("sector", ""),
                    "mktCap": p.get("mktCap") or p.get("marketCap") or 0,
                    "price": p.get("price", 0),
                    "pe": p.get("pe") or p.get("peRatio") or 0,
                    "changes": p.get("changes") or p.get("change") or 0,
                    "changesPercentage": p.get("changesPercentage") or p.get("changePercentage") or 0,
                })
            return results
        return []
    
    def get_earnings_surprises(self, ticker: str) -> List[Dict]:
        """Get earnings surprises. Tries multiple path variants."""
        for ep in ["earnings-surprises", "earnings-surprise"]:
            data = self._get(ep, {"symbol": ticker})
            if isinstance(data, list) and data:
                return data[:8]
        return []
    
    def get_income_statements(self, ticker: str) -> List[Dict]:
        data = self._get("income-statement", {"symbol": ticker, "period": "quarter", "limit": "8"})
        if isinstance(data, list):
            return data
        return []
    
    def get_insider_trades(self, ticker: str) -> List[Dict]:
        """Get insider trades via SEC EDGAR Form 4 full-text search.
        Returns data in FMP-compatible format for seamless scanner integration."""
        from_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            params = urllib.parse.urlencode({
                "q": f'"{ticker}"',
                "dateRange": "custom",
                "startdt": from_date,
                "enddt": to_date,
                "forms": "4",
            })
            url = f"https://efts.sec.gov/LATEST/search-index?{params}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "ShortSight research@shortsight.app",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                result = json.loads(resp.read().decode())
            
            hits = result.get("hits", {}).get("hits", [])
            if not hits:
                print(f"  [Insider] SEC EDGAR: 0 Form 4 filings for {ticker}")
                return []
            
            trades = []
            for h in hits[:40]:
                src = h.get("_source", {})
                names = src.get("display_names", [])
                file_date = src.get("file_date", "")
                entity = src.get("entity_name", "")
                
                # Determine transaction type from filing description
                desc = " ".join(names).lower() if names else ""
                if "disposed" in desc or "sale" in desc or "sold" in desc:
                    tx_type = "S-Sale"
                elif "acquired" in desc or "purchase" in desc or "bought" in desc:
                    tx_type = "P-Purchase"
                else:
                    tx_type = "S-Sale"  # Form 4s are most commonly sales
                
                # Try to infer role from entity name
                filer = names[0] if names else ""
                role = ""
                for title_word in ["CEO", "CFO", "COO", "CTO", "President", "Chief", "Officer", "Director", "VP"]:
                    if title_word.lower() in desc.lower():
                        role = title_word
                        break
                
                trades.append({
                    "symbol": ticker,
                    "filingDate": file_date,
                    "transactionDate": file_date,
                    "transactionType": tx_type,
                    "reportingName": filer,
                    "typeOfOwner": role or "insider",
                    "securitiesTransacted": 0,  # SEC search doesn't give share counts
                    "price": 0,  # SEC search doesn't give prices
                    "source": "SEC_EDGAR_FORM4"
                })
            
            print(f"  [Insider] SEC EDGAR: {len(trades)} Form 4 filings for {ticker}")
            return trades
            
        except Exception as e:
            print(f"  [Insider] SEC EDGAR error for {ticker}: {e}")
            return []
    
    def get_analyst_estimates(self, ticker: str) -> List[Dict]:
        """Get analyst estimates. Tries with required period/page params."""
        data = self._get("analyst-estimates", {"symbol": ticker, "period": "quarter", "page": "0", "limit": "4"})
        if isinstance(data, list) and data:
            return data
        # Fallback: try annual
        data = self._get("analyst-estimates", {"symbol": ticker, "period": "annual", "page": "0", "limit": "4"})
        if isinstance(data, list) and data:
            return data
        return []
    
    def get_analyst_recommendations(self, ticker: str) -> Dict:
        """Get analyst recommendations. Tries multiple path variants."""
        for ep in ["analyst-recommendations", "analyst-stock-recommendations", "recommendations"]:
            data = self._get(ep, {"symbol": ticker})
            if isinstance(data, list) and data:
                return data[0]
        return {}
    
    def get_price_target_consensus(self, ticker: str) -> Dict:
        data = self._get("price-target-consensus", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0]
        return {}
    
    def get_key_metrics(self, ticker: str) -> Dict:
        data = self._get("key-metrics", {"symbol": ticker, "period": "ttm"})
        # TTM might be empty, fall back to no period
        if not (isinstance(data, list) and data):
            data = self._get("key-metrics", {"symbol": ticker})
        if isinstance(data, list) and data:
            m = data[0]
            # Stable API fields differ from legacy — map what's available
            return {
                "evToSales": round(m.get("evToSales", 0) or 0, 2),
                "evToEbitda": round(m.get("evToEBITDA", 0) or 0, 2),
                "evToFreeCashFlow": round(m.get("evToFreeCashFlow", 0) or 0, 2),
                "evToOperatingCashFlow": round(m.get("evToOperatingCashFlow", 0) or 0, 2),
                "netDebtToEBITDA": round(m.get("netDebtToEBITDA", 0) or 0, 2),
                "currentRatio": round(m.get("currentRatio", 0) or 0, 2),
                "incomeQuality": round(m.get("incomeQuality", 0) or 0, 2),
                "grahamNumber": round(m.get("grahamNumber", 0) or 0, 2),
                "marketCap": m.get("marketCap", 0) or 0,
            }
        return {}
    
    def get_sp500_constituents(self) -> List[str]:
        data = self._get("sp500-constituent")
        if isinstance(data, list):
            return [item.get("symbol", "") for item in data if item.get("symbol")]
        return []
    
    def get_stock_news(self, ticker: str) -> List[Dict]:
        """Get FMP stock news for a ticker."""
        data = self._get("news/stock-latest", {"symbol": ticker, "limit": "30"})
        if not isinstance(data, list) or not data:
            return []
        
        # Check if FMP actually filtered by symbol
        # Look at the symbol field on articles
        has_symbol_field = any(item.get("symbol") for item in data[:5])
        
        if has_symbol_field:
            # Filter to articles matching this ticker's symbol
            ticker_upper = ticker.upper()
            filtered = [item for item in data if ticker_upper in (item.get("symbol","") or "").upper()]
            if filtered:
                return filtered
        
        # FMP didn't filter — return all articles (caller can filter by content)
        return data
    
    def get_general_news(self, limit: int = 50) -> List[Dict]:
        """Get general FMP stock news feed."""
        data = self._get("news/stock-latest", {"limit": str(limit)})
        if isinstance(data, list):
            return data
        return []
    
    def get_grades(self, ticker: str) -> List[Dict]:
        """Get analyst grades (upgrades/downgrades). Tries multiple path variants."""
        for ep in ["grades", "stock-grade", "grades-summary"]:
            data = self._get(ep, {"symbol": ticker, "limit": "10"})
            if isinstance(data, list) and data:
                return data
        return []
    
    def get_earnings_transcript(self, ticker: str, year: int = None, quarter: int = None) -> str:
        """Get the most recent earnings call transcript text.
        Tries FMP first, falls back to API Ninjas if configured."""
        # Try FMP - multiple path variants for transcript dates
        dates = None
        for ep in ["earning-call-transcript-available-dates", "earnings-transcript-list", "earning-transcript-dates"]:
            try:
                dates = self._get(ep, {"symbol": ticker})
                if isinstance(dates, list) and dates:
                    break
            except Exception:
                continue
        
        if isinstance(dates, list) and dates:
            latest = dates[0]
            y = year or latest.get("year") or latest.get("fiscalYear")
            q = quarter or latest.get("quarter") or latest.get("fiscalPeriod")
            if y and q:
                if isinstance(q, str):
                    q = q.replace("Q", "").strip()
                for ep in ["earning-call-transcript", "earnings-transcript"]:
                    data = self._get(ep, {"symbol": ticker, "year": str(y), "quarter": str(q)})
                    if isinstance(data, list) and data:
                        return data[0].get("content", "") or ""
                    elif isinstance(data, dict) and data.get("content"):
                        return data.get("content", "")
        
        return ""
    
    def get_share_float(self, ticker: str) -> Dict:
        """Get shares float data including short interest."""
        data = self._get("shares-float", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0]
        return {}
    
    def get_senate_trades(self, ticker: str = "") -> List[Dict]:
        """Get recent Senate trading activity. Tries multiple path variants."""
        params = {"limit": "50"}
        if ticker:
            params["symbol"] = ticker
        for ep in ["senate-trading-rss-feed", "senate-trading", "senate-disclosure", "senate-trade"]:
            data = self._get(ep, dict(params))
            if isinstance(data, list) and data:
                return data
        return []
    
    def get_house_trades(self, ticker: str = "") -> List[Dict]:
        """Get recent House trading activity. Tries multiple path variants."""
        params = {"limit": "50"}
        if ticker:
            params["symbol"] = ticker
        for ep in ["house-disclosure-rss-feed", "house-disclosure", "house-trade"]:
            data = self._get(ep, dict(params))
            if isinstance(data, list) and data:
                return data
        return []


# ═══════════════════════════════════════════
# API NINJAS — EARNINGS TRANSCRIPTS (FREE)
# ═══════════════════════════════════════════

class APINinjasTranscriptFetcher:
    """Fetches earnings call transcripts from API Ninjas (free tier)."""
    
    BASE_URL = "https://api.api-ninjas.com/v1"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def get_transcript(self, ticker: str, year: int = None, quarter: int = None) -> str:
        """Get the most recent earnings call transcript for a ticker."""
        params = {"ticker": ticker}
        if year and quarter:
            params["year"] = str(year)
            params["quarter"] = str(quarter)
        
        url = f"{self.BASE_URL}/earningstranscript?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "ShortSight/1.0"
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            
            if isinstance(data, dict):
                return data.get("transcript", "")
            return ""
        except Exception as e:
            print(f"[APINinjas] Transcript error for {ticker}: {e}")
            return ""
    
    def get_available_transcripts(self, ticker: str) -> List[Dict]:
        """Search for available transcripts for a ticker."""
        url = f"{self.BASE_URL}/earningstranscriptsearch?{urllib.parse.urlencode({'ticker': ticker})}"
        try:
            req = urllib.request.Request(url, headers={
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "ShortSight/1.0"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"[APINinjas] Transcript search error for {ticker}: {e}")
            return []


# ═══════════════════════════════════════════
# REDDIT FETCHER (PUBLIC JSON API — NO KEY)
# ═══════════════════════════════════════════

class RedditFetcher:
    """Fetches posts from Reddit's public JSON API (no auth needed)."""
    
    SUBREDDITS = ["wallstreetbets", "stocks", "investing", "stockmarket"]
    
    def search_ticker(self, ticker: str, limit: int = 25) -> List[Dict]:
        """Search Reddit for mentions of a ticker."""
        all_posts = []
        
        for sub in self.SUBREDDITS:
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json?q={ticker}&sort=new&t=week&limit={limit}&restrict_sr=on"
                req = urllib.request.Request(url, headers={
                    "User-Agent": "ShortSight/1.0 (financial research)"
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                
                children = data.get("data", {}).get("children", [])
                for child in children:
                    post = child.get("data", {})
                    # Only include if ticker is actually mentioned prominently
                    title = post.get("title", "")
                    selftext = post.get("selftext", "")[:500]
                    
                    if ticker.upper() in title.upper() or f"${ticker.upper()}" in title.upper():
                        all_posts.append({
                            "title": title[:200],
                            "text": selftext[:300],
                            "subreddit": sub,
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "url": f"https://reddit.com{post.get('permalink', '')}",
                            "created": datetime.utcfromtimestamp(
                                post.get("created_utc", 0)
                            ).isoformat() if post.get("created_utc") else "",
                            "upvote_ratio": post.get("upvote_ratio", 0)
                        })
                
            except Exception as e:
                print(f"[Reddit] Error fetching r/{sub}: {e}")
                continue
        
        return sorted(all_posts, key=lambda x: x.get("score", 0), reverse=True)
    
    def get_trending_bearish(self, limit: int = 50) -> List[Dict]:
        """Get trending bearish posts from WSB and stocks."""
        bearish_terms = ["puts", "short", "bearish", "overvalued", "crash", "dump", "sell"]
        all_posts = []
        
        for sub in ["wallstreetbets", "stocks"]:
            for term in bearish_terms[:3]:  # limit API calls
                try:
                    url = f"https://www.reddit.com/r/{sub}/search.json?q={term}&sort=hot&t=week&limit=10&restrict_sr=on"
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "ShortSight/1.0 (financial research)"
                    })
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                    
                    for child in data.get("data", {}).get("children", []):
                        post = child.get("data", {})
                        all_posts.append({
                            "title": post.get("title", "")[:200],
                            "subreddit": sub,
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "url": f"https://reddit.com{post.get('permalink', '')}",
                            "created": datetime.utcfromtimestamp(
                                post.get("created_utc", 0)
                            ).isoformat() if post.get("created_utc") else "",
                        })
                except Exception:
                    continue
        
        # Deduplicate by title
        seen = set()
        unique = []
        for p in all_posts:
            if p["title"] not in seen:
                seen.add(p["title"])
                unique.append(p)
        
        return sorted(unique, key=lambda x: x.get("score", 0), reverse=True)[:limit]


# ═══════════════════════════════════════════
# SEC EDGAR FETCHER (FREE, NO KEY)
# ═══════════════════════════════════════════

class SECFetcher:
    """Fetches filings from SEC EDGAR (free, no API key required)."""
    
    EDGAR_BASE = "https://efts.sec.gov/LATEST"
    
    def search_filings(self, ticker: str, form_types: List[str] = None) -> List[Dict]:
        """Search for recent SEC filings by ticker."""
        if form_types is None:
            form_types = ["8-K", "4"]
        
        filings = []
        for form_type in form_types:
            try:
                params = {
                    "q": ticker,
                    "dateRange": "custom",
                    "startdt": (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"),
                    "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
                    "forms": form_type,
                }
                url = f"{self.EDGAR_BASE}/search-index?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(url, headers={
                    "User-Agent": "ShortSight research@shortsight.app",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                
                hits = data.get("hits", {}).get("hits", [])
                for hit in hits[:20]:
                    source = hit.get("_source", {})
                    filings.append({
                        "form_type": source.get("form_type", form_type),
                        "filed_date": source.get("file_date", ""),
                        "company": source.get("entity_name", ""),
                        "description": source.get("display_names", [""])[0] if source.get("display_names") else "",
                    })
            except Exception as e:
                print(f"[SEC] Error fetching {form_type} for {ticker}: {e}")
        return filings
    
    def get_material_events(self, ticker: str) -> List[Dict]:
        return self.search_filings(ticker, ["8-K"])


# ═══════════════════════════════════════════
# UNUSUAL WHALES FETCHER (PAID — OPTIONS FLOW + DARK POOL)
# ═══════════════════════════════════════════

class UnusualWhalesFetcher:
    """Fetches options flow and dark pool data from Unusual Whales API."""
    
    BASE_URL = "https://api.unusualwhales.com/api"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def _get(self, endpoint: str, params: Dict = None) -> any:
        if params is None:
            params = {}
        url = f"{self.BASE_URL}/{endpoint}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "ShortSight/1.0"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[UW] Error {endpoint}: {e}")
            return {}
    
    def get_options_flow(self, ticker: str) -> List[Dict]:
        """Get recent options flow for a ticker."""
        data = self._get(f"stock/{ticker}/flow-recent")
        return data.get("data", []) if isinstance(data, dict) else []
    
    def get_flow_alerts(self) -> List[Dict]:
        """Get flow alerts (unusual options activity)."""
        data = self._get("option-trades/flow-alerts")
        return data.get("data", []) if isinstance(data, dict) else []
    
    def get_darkpool(self, ticker: str) -> List[Dict]:
        """Get dark pool prints for a ticker."""
        data = self._get(f"darkpool/{ticker}")
        return data.get("data", []) if isinstance(data, dict) else []
    
    def get_market_tide(self) -> Dict:
        """Get overall market sentiment (net premium, put/call)."""
        data = self._get("market/market-tide")
        return data.get("data", {}) if isinstance(data, dict) else {}
    
    def get_ticker_options_summary(self, ticker: str) -> Dict:
        """Get put/call ratio and net premium for a ticker."""
        flow = self.get_options_flow(ticker)
        if not flow:
            return {}
        
        total_puts = 0
        total_calls = 0
        put_premium = 0
        call_premium = 0
        large_puts = 0  # premium > $100k
        
        for trade in flow:
            option_type = (trade.get("put_call", "") or trade.get("option_type", "")).upper()
            premium = float(trade.get("premium", 0) or 0)
            
            if option_type == "PUT":
                total_puts += 1
                put_premium += premium
                if premium > 100_000:
                    large_puts += 1
            elif option_type == "CALL":
                total_calls += 1
                call_premium += premium
        
        total = total_puts + total_calls
        return {
            "put_call_ratio": round(total_puts / max(total_calls, 1), 2),
            "total_puts": total_puts,
            "total_calls": total_calls,
            "put_premium": put_premium,
            "call_premium": call_premium,
            "net_premium": call_premium - put_premium,
            "large_put_trades": large_puts,
            "total_trades": total,
            "put_pct": round(total_puts / max(total, 1) * 100, 1),
        }


# ═══════════════════════════════════════════
# QUIVER QUANTITATIVE FETCHER ($10/mo)
# ═══════════════════════════════════════════

class QuiverFetcher:
    """Fetches alternative data from Quiver Quantitative API."""
    
    BASE_URL = "https://api.quiverquant.com/beta"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def _get(self, endpoint: str) -> any:
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "ShortSight/1.0"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[Quiver] Error {endpoint}: {e}")
            return []
    
    def get_wsb_mentions(self, ticker: str) -> List[Dict]:
        """Get WallStreetBets discussion data for a ticker."""
        data = self._get(f"historical/wallstreetbets/{ticker}")
        if isinstance(data, list):
            return data[:30]
        return []
    
    def get_congress_trading(self, ticker: str) -> List[Dict]:
        """Get congressional trading for a ticker."""
        data = self._get(f"historical/congresstrading/{ticker}")
        if isinstance(data, list):
            return data[:30]
        return []
    
    def get_off_exchange(self, ticker: str) -> List[Dict]:
        """Get off-exchange (dark pool) short volume."""
        data = self._get(f"historical/offexchange/{ticker}")
        if isinstance(data, list):
            return data[:30]
        return []
    
    def get_wikipedia(self, ticker: str) -> List[Dict]:
        """Get Wikipedia page view trends (unusual spikes can precede events)."""
        data = self._get(f"historical/wikipedia/{ticker}")
        if isinstance(data, list):
            return data[:30]
        return []
    
    def get_lobbying(self, ticker: str) -> List[Dict]:
        """Get corporate lobbying activity."""
        data = self._get(f"historical/lobbying/{ticker}")
        if isinstance(data, list):
            return data[:10]
        return []


# ═══════════════════════════════════════════
# STOCKTWITS FETCHER (FREE — NO AUTH)
# ═══════════════════════════════════════════

class StocktwitsFetcher:
    """Fetches sentiment data from Stocktwits public API."""
    
    BASE_URL = "https://api.stocktwits.com/api/2"
    
    def get_ticker_stream(self, ticker: str) -> Dict:
        """Get message stream and sentiment for a ticker."""
        try:
            url = f"{self.BASE_URL}/streams/symbol/{ticker}.json"
            req = urllib.request.Request(url, headers={
                "User-Agent": "ShortSight/1.0",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[Stocktwits] Error for {ticker}: {e}")
            return {}
    
    def get_sentiment_summary(self, ticker: str) -> Dict:
        """Analyze Stocktwits sentiment for a ticker."""
        data = self.get_ticker_stream(ticker)
        
        symbol_info = data.get("symbol", {})
        messages = data.get("messages", [])
        
        if not messages:
            return {"bullish": 0, "bearish": 0, "total": 0, "bearish_pct": 0}
        
        bullish = 0
        bearish = 0
        total = len(messages)
        
        for msg in messages:
            sentiment = msg.get("entities", {}).get("sentiment", {})
            if sentiment:
                basic = sentiment.get("basic", "")
                if basic == "Bullish":
                    bullish += 1
                elif basic == "Bearish":
                    bearish += 1
        
        labeled = bullish + bearish
        bearish_pct = round(bearish / max(labeled, 1) * 100, 1)
        
        # Watchlist count can indicate attention
        watchers = symbol_info.get("watchlist_count", 0)
        
        return {
            "bullish": bullish,
            "bearish": bearish,
            "total": total,
            "labeled": labeled,
            "bearish_pct": bearish_pct,
            "bullish_pct": round(bullish / max(labeled, 1) * 100, 1),
            "watchers": watchers,
            "sentiment_label": symbol_info.get("sentiment", ""),
        }

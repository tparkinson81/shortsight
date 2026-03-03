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
        except Exception as e:
            print(f"[FMP] Error {endpoint}: {e}")
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
            }
        return {"companyName": ticker}
    
    def get_batch_profiles(self, tickers: List[str]) -> List[Dict]:
        """Get profiles for multiple tickers in one call."""
        tickers_str = ",".join(tickers)
        data = self._get("profile", {"symbol": tickers_str})
        if isinstance(data, list):
            return data
        return []
    
    def get_earnings_surprises(self, ticker: str) -> List[Dict]:
        data = self._get("earnings-surprises", {"symbol": ticker})
        if isinstance(data, list):
            return data[:8]
        return []
    
    def get_income_statements(self, ticker: str) -> List[Dict]:
        data = self._get("income-statement", {"symbol": ticker, "period": "quarter", "limit": "8"})
        if isinstance(data, list):
            return data
        return []
    
    def get_insider_trades(self, ticker: str) -> List[Dict]:
        data = self._get("insider-trading", {"symbol": ticker, "limit": "50"})
        if isinstance(data, list):
            return data
        return []
    
    def get_analyst_estimates(self, ticker: str) -> List[Dict]:
        data = self._get("analyst-estimates", {"symbol": ticker, "limit": "4"})
        if isinstance(data, list):
            return data
        return []
    
    def get_analyst_recommendations(self, ticker: str) -> Dict:
        data = self._get("analyst-recommendations", {"symbol": ticker})
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
        if isinstance(data, list) and data:
            m = data[0]
            return {
                "peRatio": round(m.get("peRatio", 0) or 0, 2),
                "pbRatio": round(m.get("pbRatio", 0) or 0, 2),
                "priceToSalesRatio": round(m.get("priceToSalesRatio", 0) or 0, 2),
                "evToEbitda": round(m.get("enterpriseValueOverEBITDA", 0) or 0, 2),
                "pegRatio": round(m.get("pegRatio", 0) or 0, 2),
                "debtToEquity": round(m.get("debtToEquity", 0) or 0, 2),
                "roe": round((m.get("roe", 0) or 0) * 100, 2),
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
        if isinstance(data, list):
            return data
        return []
    
    def get_general_news(self, limit: int = 50) -> List[Dict]:
        """Get general FMP stock news feed."""
        data = self._get("news/stock-latest", {"limit": str(limit)})
        if isinstance(data, list):
            return data
        return []
    
    def get_grades(self, ticker: str) -> List[Dict]:
        """Get analyst grades (upgrades/downgrades)."""
        data = self._get("stock-grade", {"symbol": ticker, "limit": "10"})
        if isinstance(data, list):
            return data
        return []
    
    def get_earnings_transcript(self, ticker: str, year: int = None, quarter: int = None) -> str:
        """Get the most recent earnings call transcript text."""
        # First get available dates
        dates = self._get("earning-call-transcript-available-dates", {"symbol": ticker})
        if not isinstance(dates, list) or not dates:
            return ""
        
        # Use most recent
        latest = dates[0]
        y = year or latest.get("year") or latest.get("fiscalYear")
        q = quarter or latest.get("quarter") or latest.get("fiscalPeriod")
        if not y or not q:
            return ""
        
        # Normalize quarter — handle "Q1" vs 1
        if isinstance(q, str):
            q = q.replace("Q", "").strip()
        
        data = self._get("earning-call-transcript", {"symbol": ticker, "year": str(y), "quarter": str(q)})
        if isinstance(data, list) and data:
            return data[0].get("content", "") or ""
        elif isinstance(data, dict):
            return data.get("content", "") or ""
        return ""
    
    def get_share_float(self, ticker: str) -> Dict:
        """Get shares float data including short interest."""
        data = self._get("shares-float", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0]
        return {}
    
    def get_senate_trades(self, ticker: str = "") -> List[Dict]:
        """Get recent Senate trading activity."""
        params = {"limit": "50"}
        if ticker:
            params["symbol"] = ticker
        data = self._get("senate-trading-rss-feed", params)
        if isinstance(data, list):
            return data
        return []
    
    def get_house_trades(self, ticker: str = "") -> List[Dict]:
        """Get recent House trading activity."""
        params = {"limit": "50"}
        if ticker:
            params["symbol"] = ticker
        data = self._get("house-disclosure-rss-feed", params)
        if isinstance(data, list):
            return data
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

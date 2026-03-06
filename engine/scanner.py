"""
ShortSight — Scanner Engine
Orchestrates data from all sources and scores tickers for short potential.

Scoring (0-100 bearish conviction):
  News Sentiment:        20 pts
  Earnings Transcript:   15 pts
  Insider Activity:      15 pts
  Earnings Quality:      15 pts
  Short Interest:        10 pts
  Congressional Trading: 10 pts
  Social Sentiment:      10 pts
  Analyst Momentum:       5 pts
"""

import os
import json
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from engine.sentiment import SentimentEngine
from engine.fetchers import NewsFetcher, FMPFetcher, RedditFetcher, SECFetcher, UnusualWhalesFetcher, QuiverFetcher, StocktwitsFetcher, APINinjasTranscriptFetcher


@dataclass
class ShortCandidate:
    ticker: str
    company_name: str = ""
    sector: str = ""
    price: float = 0.0
    price_change_pct: float = 0.0
    
    total_score: int = 0
    conviction: str = ""  # Weak / Moderate / Strong / Very Strong
    
    news_score: int = 0
    transcript_score: int = 0
    insider_score: int = 0
    earnings_score: int = 0
    short_interest_score: int = 0
    valuation_score: int = 0
    price_action_score: int = 0
    social_score: int = 0
    sec_score: int = 0
    analyst_score: int = 0
    
    news_flags: List[str] = field(default_factory=list)
    transcript_flags: List[str] = field(default_factory=list)
    insider_flags: List[str] = field(default_factory=list)
    earnings_flags: List[str] = field(default_factory=list)
    short_interest_flags: List[str] = field(default_factory=list)
    valuation_flags: List[str] = field(default_factory=list)
    price_action_flags: List[str] = field(default_factory=list)
    social_flags: List[str] = field(default_factory=list)
    sec_flags: List[str] = field(default_factory=list)
    analyst_flags: List[str] = field(default_factory=list)
    
    top_headlines: List[Dict] = field(default_factory=list)
    reddit_posts: List[Dict] = field(default_factory=list)
    
    summary: str = ""
    risks: List[str] = field(default_factory=list)
    catalyst: str = ""
    generated_at: str = ""


class ShortScanner:
    """Main scanner that analyzes tickers across all data sources."""
    
    def __init__(self, news_key: str, fmp_key: str, uw_key: str = "", quiver_key: str = "", apininjas_key: str = ""):
        self.news = NewsFetcher(news_key)
        self.fmp = FMPFetcher(fmp_key)
        self.reddit = RedditFetcher()
        self.sec = SECFetcher()
        self.sentiment = SentimentEngine()
        self.stocktwits = StocktwitsFetcher()
        
        # Optional paid sources
        self.uw = UnusualWhalesFetcher(uw_key) if uw_key else None
        self.quiver = QuiverFetcher(quiver_key) if quiver_key else None
        
        # API Ninjas for transcript fallback
        self.apininjas = APINinjasTranscriptFetcher(apininjas_key) if apininjas_key else None
        
        self.results_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "scan_results.json"
        )
    
    # ── NEWS SENTIMENT (25 pts) ──
    
    def score_news(self, ticker: str, company_name: str = "") -> Tuple[int, List[str], List[Dict]]:
        score = 0
        flags = []
        
        # Get news from both NewsAPI and FMP
        articles = []
        try:
            newsapi_articles = self.news.get_ticker_news(ticker, company_name, days=7)
            articles.extend(newsapi_articles or [])
        except Exception as e:
            print(f"  [News] NewsAPI error for {ticker}: {e}")
        
        try:
            # FMP news endpoint returns ALL news regardless of symbol param
            # So we pull general news and filter by the symbol field on each article
            fmp_news = self.fmp._get("news/stock-latest", {"limit": "200"})
            ticker_upper = ticker.upper()
            for item in (fmp_news or []):
                article_sym = (item.get("symbol","") or "").upper()
                if article_sym == ticker_upper:
                    articles.append({
                        "title": item.get("title", ""),
                        "description": item.get("text", ""),
                        "source": {"name": item.get("site", "")},
                        "url": item.get("url", ""),
                        "publishedAt": item.get("publishedDate", "")
                    })
        except Exception as e:
            print(f"  [News] FMP news error for {ticker}: {e}")
        
        if not articles:
            return 0, [], []
        
        # Score all articles
        result = self.sentiment.score_headlines(articles, ticker)
        
        agg = result["aggregate_score"]
        bearish_ratio = result.get("bearish_ratio", 0)
        bearish_count = result.get("bearish_count", 0)
        
        # Score based on aggregate
        if agg <= -0.5:
            score += 15
            flags.append(f"Strongly negative news sentiment ({agg:+.2f}) across {result['article_count']} articles")
        elif agg <= -0.3:
            score += 10
            flags.append(f"Negative news sentiment ({agg:+.2f})")
        elif agg <= -0.15:
            score += 5
            flags.append(f"Mildly negative news sentiment ({agg:+.2f})")
        
        # Bonus for high bearish ratio
        if bearish_ratio > 0.6 and bearish_count >= 5:
            score += 7
            flags.append(f"{bearish_count} of {result['article_count']} articles bearish ({bearish_ratio:.0%}) — consistent negative narrative")
        elif bearish_ratio > 0.4 and bearish_count >= 3:
            score += 4
            flags.append(f"{bearish_ratio:.0%} of recent articles bearish")
        
        # Check for specific high-impact signals in top articles
        top_signals = []
        for art in result.get("articles", [])[:10]:
            for sig in art.get("sentiment", {}).get("signals", []):
                if sig["score"] < -0.5:
                    top_signals.append(sig["phrase"])
        
        if top_signals:
            unique = list(set(top_signals))[:3]
            score += min(len(unique) * 2, 5)
            flags.append(f"Key red flags detected: {', '.join(unique)}")
        
        # Top 5 most bearish headlines for display
        top_headlines = []
        for art in result.get("articles", [])[:5]:
            if art["sentiment"]["score"] < 0:
                top_headlines.append({
                    "title": art["title"],
                    "source": art["source"],
                    "score": art["sentiment"]["score"],
                    "published": art["published"]
                })
        
        return min(score, 20), flags, top_headlines
    
    # ── EARNINGS TRANSCRIPT (15 pts) ──
    
    def score_transcript(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        try:
            # Try FMP first
            transcript = self.fmp.get_earnings_transcript(ticker)
            
            # Fallback to API Ninjas if FMP returns nothing
            if (not transcript or len(transcript) < 200) and self.apininjas:
                print(f"  [Transcript] FMP empty, trying API Ninjas for {ticker}...")
                transcript = self.apininjas.get_transcript(ticker)
                if transcript and len(transcript) >= 200:
                    print(f"  [Transcript] Got {len(transcript)} chars from API Ninjas")
            
            if not transcript or len(transcript) < 200:
                return 0, []
            
            result = self.sentiment.score_transcript(transcript)
            
            # Score based on transcript analysis
            t_score = result["score"]
            if t_score <= -0.6:
                score += 10
            elif t_score <= -0.3:
                score += 6
            elif t_score <= -0.15:
                score += 3
            
            # Hedging bonus
            if result["hedging_ratio"] > 2:
                score += 3
            elif result["hedging_ratio"] > 1:
                score += 1
            
            # Buzzword bonus
            if result["buzzword_ratio"] > 3:
                score += 2
            
            flags.extend(result.get("flags", []))
            
        except Exception as e:
            print(f"  [Transcript] Error for {ticker}: {e}")
        
        return min(score, 15), flags
    
    # ── INSIDER ACTIVITY (20 pts) ──
    
    def score_insiders(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        trades = self.fmp.get_insider_trades(ticker)
        if not trades:
            return 0, []
        
        cutoff = datetime.utcnow() - timedelta(days=90)
        total_sold = 0
        total_bought = 0
        csuite_sells = 0
        csuite_value = 0
        sell_filings = 0
        buy_filings = 0
        is_sec_edgar = any(t.get("source") == "SEC_EDGAR_FORM4" for t in trades)
        
        csuite_titles = ["ceo", "cfo", "coo", "cto", "president", "chief", "officer"]
        
        for trade in trades:
            try:
                date_str = (trade.get("filingDate", "") or trade.get("transactionDate", ""))[:10]
                if not date_str:
                    continue
                trade_date = datetime.strptime(date_str, "%Y-%m-%d")
                if trade_date < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            
            tx = (trade.get("transactionType", "") or "").lower()
            shares = abs(trade.get("securitiesTransacted", 0) or 0)
            price = trade.get("price", 0) or 0
            value = shares * price
            name = (trade.get("reportingName", "") or "").lower()
            title = (trade.get("typeOfOwner", "") or "").lower()
            
            if any(t in tx for t in ["sale", "sell", "s-sale", "s - sale"]):
                total_sold += value
                sell_filings += 1
                if any(t in (name + " " + title) for t in csuite_titles):
                    csuite_sells += 1
                    csuite_value += value
            elif any(t in tx for t in ["purchase", "buy", "p-purchase"]):
                total_bought += value
                buy_filings += 1
        
        if is_sec_edgar:
            # SEC EDGAR mode: score based on filing counts (no dollar amounts)
            total_filings = sell_filings + buy_filings
            if sell_filings > 0 and buy_filings == 0 and sell_filings >= 5:
                score += 8
                flags.append(f"{sell_filings} insider sell filings vs 0 buy filings (90d)")
            elif sell_filings > buy_filings * 3 and sell_filings >= 4:
                score += 6
                flags.append(f"Insider sell filings outnumber buys {sell_filings}:{buy_filings}")
            elif sell_filings > buy_filings * 2 and sell_filings >= 3:
                score += 4
                flags.append(f"Insider selling trend: {sell_filings} sells vs {buy_filings} buys")
            elif sell_filings >= 2:
                score += 2
                flags.append(f"{sell_filings} insider sell filings in 90 days")
            
            if csuite_sells >= 2:
                score += 7
                flags.append(f"{csuite_sells} C-suite/officer sell filings — executives reducing exposure")
            elif csuite_sells >= 1:
                score += 3
                flags.append(f"C-suite insider selling detected")
        else:
            # FMP mode: score based on dollar amounts
            sell_ratio = total_sold / max(total_bought, 1)
            
            if sell_ratio > 10 and total_sold > 1_000_000:
                score += 10
                flags.append(f"Heavy insider selling: ${total_sold/1e6:.1f}M sold vs ${total_bought/1e6:.1f}M bought (90d)")
            elif sell_ratio > 5 and total_sold > 500_000:
                score += 6
                flags.append(f"Insider selling outpacing buying {sell_ratio:.0f}:1")
            elif sell_ratio > 3:
                score += 3
                flags.append(f"Insider sell/buy ratio: {sell_ratio:.0f}:1")
            
            if csuite_sells >= 3:
                score += 10
                flags.append(f"{csuite_sells} C-suite sell transactions (${csuite_value/1e6:.1f}M) — executives reducing exposure")
            elif csuite_sells >= 1 and csuite_value > 500_000:
                score += 5
                flags.append(f"C-suite sold ${csuite_value/1e6:.1f}M in stock")
        
        return min(score, 15), flags
    
    # ── EARNINGS QUALITY (15 pts) ──
    
    def score_earnings(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        # Income statement trends (working on Premium)
        stmts = self.fmp.get_income_statements(ticker)
        if stmts and len(stmts) >= 2:
            revenues = [s.get("revenue", 0) or 0 for s in stmts[:4]]
            margins = []
            net_incomes = []
            for s in stmts[:4]:
                rev = s.get("revenue", 0) or 0
                gp = s.get("grossProfit", 0) or 0
                ni = s.get("netIncome", 0) or 0
                if rev > 0:
                    margins.append(round((gp / rev) * 100, 1))
                net_incomes.append(ni)
            
            # Revenue deceleration
            if len(revenues) >= 2 and revenues[1] > 0:
                growth = ((revenues[0] - revenues[1]) / abs(revenues[1])) * 100
                if growth < -10:
                    score += 7
                    flags.append(f"Revenue contracting sharply {growth:.1f}% QoQ")
                elif growth < -5:
                    score += 5
                    flags.append(f"Revenue contracting {growth:.1f}% QoQ")
                elif growth < 0:
                    score += 3
                    flags.append(f"Revenue declining {growth:.1f}% QoQ")
            
            # Margin compression
            if len(margins) >= 2 and margins[-1] > margins[0] + 3:
                score += 4
                flags.append(f"Gross margins compressing: {margins[-1]:.1f}% → {margins[0]:.1f}%")
            
            # Net income declining
            if len(net_incomes) >= 2 and net_incomes[1] > 0:
                if net_incomes[0] < 0 and net_incomes[1] > 0:
                    score += 5
                    flags.append(f"Swung to net loss from profit last quarter")
                elif net_incomes[0] < net_incomes[1] * 0.7:
                    score += 3
                    flags.append(f"Net income dropped {((net_incomes[0] - net_incomes[1]) / abs(net_incomes[1])) * 100:.0f}% QoQ")
            
            # Multi-quarter revenue decline
            if len(revenues) >= 3 and all(revenues[i] < revenues[i+1] for i in range(min(len(revenues)-1, 2))):
                score += 3
                flags.append(f"Revenue declining for {min(len(revenues), 3)} consecutive quarters")
        
        return min(score, 15), flags
    
    # ── SHORT INTEREST (10 pts) ──
    
    def score_short_interest(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        try:
            data = self.fmp.get_share_float(ticker)
            if not data:
                return 0, []
            
            # Stable API only provides float data, not short interest
            # But low free float amplifies short squeeze risk — useful signal
            free_float = data.get("freeFloat") or 0
            float_shares = data.get("floatShares") or 0
            outstanding = data.get("outstandingShares") or 0
            
            # Low free float = higher volatility, easier to squeeze
            if 0 < free_float < 30:
                score += 3
                flags.append(f"Low free float: {free_float:.1f}% — limited supply amplifies moves")
            elif 0 < free_float < 50:
                score += 1
                flags.append(f"Free float: {free_float:.1f}%")
            
            # Also try the short interest fields in case they exist on higher plans
            short_pct = data.get("shortPercentOfSharesOutstanding") or data.get("shortPercentFloat") or 0
            short_ratio = data.get("shortRatio") or data.get("daysToCover") or 0
            
            if isinstance(short_pct, (int, float)) and short_pct > 0:
                if short_pct < 1:
                    short_pct = short_pct * 100
                
                if short_pct > 20:
                    score += 5
                    flags.append(f"Very high short interest: {short_pct:.1f}% of float — already heavily shorted")
                elif short_pct > 10:
                    score += 3
                    flags.append(f"Elevated short interest: {short_pct:.1f}% of float")
                elif short_pct > 5:
                    score += 1
                    flags.append(f"Notable short interest: {short_pct:.1f}% of float")
            
            if isinstance(short_ratio, (int, float)) and short_ratio > 0:
                if short_ratio > 10:
                    score += 5
                    flags.append(f"Days to cover: {short_ratio:.1f} — very difficult to cover, squeeze risk elevated")
                elif short_ratio > 5:
                    score += 3
                    flags.append(f"Days to cover: {short_ratio:.1f}")
                elif short_ratio > 3:
                    score += 1
                    flags.append(f"Days to cover: {short_ratio:.1f}")
        except Exception as e:
            print(f"  [ShortInterest] Error for {ticker}: {e}")
        
        return min(score, 10), flags
    
    # ── VALUATION (15 pts) — key-metrics ──
    
    def score_valuation(self, ticker: str, profile: Dict) -> Tuple[int, List[str]]:
        """Score overvaluation signals from key metrics."""
        score = 0
        flags = []
        
        try:
            m = self.fmp.get_key_metrics(ticker)
            if not m:
                return 0, []
            
            ev_sales = m.get("evToSales", 0)
            ev_ebitda = m.get("evToEbitda", 0)
            ev_fcf = m.get("evToFreeCashFlow", 0)
            net_debt_ebitda = m.get("netDebtToEBITDA", 0)
            graham = m.get("grahamNumber", 0)
            price = profile.get("price", 0) or 0
            
            # EV/Sales
            if ev_sales > 20:
                score += 4
                flags.append(f"Extreme EV/Sales: {ev_sales:.1f}x — revenue multiple stretched")
            elif ev_sales > 10:
                score += 3
                flags.append(f"High EV/Sales: {ev_sales:.1f}x")
            elif ev_sales > 6:
                score += 1
                flags.append(f"Elevated EV/Sales: {ev_sales:.1f}x")
            
            # EV/EBITDA
            if ev_ebitda > 50:
                score += 4
                flags.append(f"EV/EBITDA: {ev_ebitda:.0f}x — extremely expensive")
            elif ev_ebitda > 30:
                score += 3
                flags.append(f"EV/EBITDA: {ev_ebitda:.0f}x — rich valuation")
            elif ev_ebitda > 20:
                score += 1
                flags.append(f"EV/EBITDA: {ev_ebitda:.0f}x")
            elif ev_ebitda < 0:
                score += 2
                flags.append(f"Negative EBITDA (EV/EBITDA: {ev_ebitda:.0f}x)")
            
            # EV/FCF
            if ev_fcf > 100:
                score += 3
                flags.append(f"EV/FCF: {ev_fcf:.0f}x — extreme cash flow multiple")
            elif ev_fcf > 50:
                score += 2
                flags.append(f"EV/FCF: {ev_fcf:.0f}x — expensive on cash flow basis")
            elif ev_fcf < 0:
                score += 2
                flags.append(f"Negative free cash flow (EV/FCF: {ev_fcf:.0f}x)")
            
            # Graham Number
            if graham > 0 and price > 0 and price > graham * 3:
                score += 3
                flags.append(f"Price ${price:.0f} is {price/graham:.1f}x Graham Number (${graham:.0f})")
            elif graham > 0 and price > graham * 2:
                score += 2
                flags.append(f"Trading at {price/graham:.1f}x Graham Number")
            elif graham > 0 and price > graham * 1.5:
                score += 1
                flags.append(f"Above Graham Number ({price/graham:.1f}x)")
            
        except Exception as e:
            print(f"  [Valuation] Error for {ticker}: {e}")
        
        return min(score, 15), flags
    
    # ── SOCIAL SENTIMENT (10 pts) — Reddit + Stocktwits + Quiver WSB ──
    
    def score_social(self, ticker: str) -> Tuple[int, List[str], List[Dict]]:
        score = 0
        flags = []
        posts = []
        
        # Reddit
        try:
            posts = self.reddit.search_ticker(ticker, limit=20)
        except Exception as e:
            print(f"  [Reddit] Error for {ticker}: {e}")
        
        # Stocktwits
        try:
            st = self.stocktwits.get_sentiment_summary(ticker)
            if st.get("labeled", 0) >= 5:
                bearish_pct = st.get("bearish_pct", 0)
                if bearish_pct > 65:
                    score += 4
                    flags.append(f"Stocktwits heavily bearish: {bearish_pct:.0f}% bearish ({st['bearish']}/{st['labeled']} labeled posts)")
                elif bearish_pct > 50:
                    score += 2
                    flags.append(f"Stocktwits leaning bearish: {bearish_pct:.0f}%")
        except Exception as e:
            print(f"  [Stocktwits] Error for {ticker}: {e}")
        
        # Quiver WSB data
        if self.quiver:
            try:
                wsb = self.quiver.get_wsb_mentions(ticker)
                if wsb and len(wsb) >= 2:
                    recent = wsb[0].get("Mentions", 0) or 0
                    prev = wsb[1].get("Mentions", 0) or 0
                    if recent > prev * 3 and recent > 10:
                        score += 2
                        flags.append(f"WSB mention spike: {recent} mentions (was {prev}) — unusual attention")
            except Exception as e:
                print(f"  [Quiver WSB] Error for {ticker}: {e}")
        
        # Reddit scoring
        if posts:
            bearish = 0
            total = len(posts)
            bearish_keywords = ["puts", "short", "bearish", "overvalued", "dump", "sell", "crash",
                               "fraud", "scam", "bubble", "bag holding", "exit"]
            for post in posts:
                text = (post.get("title", "") + " " + post.get("text", "")).lower()
                if any(kw in text for kw in bearish_keywords):
                    bearish += 1
            
            if total > 0:
                bearish_pct = bearish / total
                if bearish_pct > 0.5 and total >= 5:
                    score += 3
                    flags.append(f"Reddit bearish: {bearish}/{total} posts negative")
                elif bearish_pct > 0.3 and total >= 3:
                    score += 1
                    flags.append(f"Some bearish Reddit posts ({bearish}/{total})")
        
        return min(score, 10), flags, posts[:5]
    
    # ── SEC FILINGS (10 pts) ──
    
    def score_sec(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        try:
            filings = self.sec.get_material_events(ticker)
            if filings:
                recent_8k = len(filings)
                if recent_8k >= 5:
                    score += 5
                    flags.append(f"{recent_8k} material event (8-K) filings in 90 days — unusual activity")
                elif recent_8k >= 3:
                    score += 3
                    flags.append(f"{recent_8k} recent 8-K filings")
                
                # Check descriptions for red flags
                red_flags_8k = ["departure", "resignation", "termination", "material weakness",
                               "non-reliance", "restatement", "amendment", "going concern",
                               "default", "delisting"]
                for f in filings:
                    desc = (f.get("description", "") or "").lower()
                    for rf in red_flags_8k:
                        if rf in desc:
                            score += 3
                            flags.append(f"8-K red flag: \"{rf}\" — {f.get('filed_date', '')}")
                            break
        except Exception as e:
            print(f"  [SEC] Error for {ticker}: {e}")
        
        return min(score, 10), flags
    
    # ── PRICE ACTION (10 pts) — drawdown, 52-week proximity ──
    
    def score_price_action(self, ticker: str, price: float, profile: Dict) -> Tuple[int, List[str]]:
        """Score bearish price action signals."""
        score = 0
        flags = []
        
        try:
            # 52-week range from profile
            range_str = profile.get("range", "")
            if range_str and "-" in range_str:
                parts = range_str.split("-")
                try:
                    low_52w = float(parts[0].strip())
                    high_52w = float(parts[1].strip())
                except (ValueError, IndexError):
                    low_52w = 0
                    high_52w = 0
                
                if high_52w > 0 and price > 0:
                    # How far from 52-week high (drawdown %)
                    drawdown = ((price - high_52w) / high_52w) * 100
                    
                    if drawdown < -40:
                        score += 4
                        flags.append(f"Down {abs(drawdown):.0f}% from 52-week high (${high_52w:.2f}) — deep drawdown")
                    elif drawdown < -25:
                        score += 3
                        flags.append(f"Down {abs(drawdown):.0f}% from 52-week high (${high_52w:.2f})")
                    elif drawdown < -15:
                        score += 2
                        flags.append(f"Down {abs(drawdown):.0f}% from 52-week high")
                    
                    # Proximity to 52-week low (approaching floor = momentum breakdown)
                    if low_52w > 0:
                        range_width = high_52w - low_52w
                        if range_width > 0:
                            position = (price - low_52w) / range_width  # 0 = at low, 1 = at high
                            if position < 0.15:
                                score += 3
                                flags.append(f"Trading near 52-week low (${low_52w:.2f}) — bottom {position*100:.0f}% of range")
                            elif position < 0.30:
                                score += 2
                                flags.append(f"In lower third of 52-week range")
            
            # Recent price momentum (changesPercentage = today's move, but changes = raw $ change)
            changes_pct = profile.get("changesPercentage", 0) or 0
            if changes_pct < -5:
                score += 2
                flags.append(f"Sharp recent decline: {changes_pct:.1f}%")
            elif changes_pct < -2:
                score += 1
                flags.append(f"Recent weakness: {changes_pct:.1f}%")
            
            # High beta = amplified downside risk
            beta = profile.get("beta", 1.0) or 1.0
            if beta > 2.0:
                score += 1
                flags.append(f"High beta ({beta:.1f}) — amplified downside risk")
            
        except Exception as e:
            print(f"  [PriceAction] Error for {ticker}: {e}")
        
        return min(score, 10), flags
    
    # ── ANALYST MOMENTUM (5 pts) ──
    
    def score_analysts(self, ticker: str, price: float) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        # Recommendations
        recs = self.fmp.get_analyst_recommendations(ticker)
        if recs:
            sell = (recs.get("analystRatingsSell", 0) or 0) + (recs.get("analystRatingsStrongSell", 0) or 0)
            buy = (recs.get("analystRatingsBuy", 0) or 0) + (recs.get("analystRatingsStrongBuy", 0) or 0)
            hold = recs.get("analystRatingsHold", 0) or 0
            total = sell + buy + hold
            
            if total > 0:
                bearish_pct = sell / total
                if bearish_pct > 0.3:
                    score += 3
                    flags.append(f"{bearish_pct:.0%} of analysts rate Sell — unusual bearish consensus")
                elif bearish_pct > 0.15:
                    score += 1
                    flags.append(f"{bearish_pct:.0%} analyst sell ratings")
            
            # Price target from same endpoint if available
            consensus = recs.get("targetConsensus") or recs.get("targetPrice", 0)
            if consensus and consensus > 0 and price > 0:
                upside = ((consensus - price) / price) * 100
                if upside < -10:
                    score += 2
                    flags.append(f"Trading {abs(upside):.0f}% ABOVE consensus target (${consensus:.0f})")
                elif upside < 0:
                    score += 1
                    flags.append(f"Above consensus price target (${consensus:.0f})")
            flags.append(f"Recent analyst downgrade(s)")
        
        return min(score, 5), flags
    
    # ── THESIS GENERATOR ──
    
    def generate_summary(self, c: ShortCandidate) -> str:
        """Generate plain-English short thesis focused on strongest signals."""
        dim_maxes = {"news":20,"transcript":15,"insider":15,"earnings":15,"short_interest":10,
                     "valuation":15,"price_action":10,"social":10,"sec":10,"analyst":5}
        dim_scores = {"news":c.news_score,"transcript":c.transcript_score,"insider":c.insider_score,
                      "earnings":c.earnings_score,"short_interest":c.short_interest_score,
                      "valuation":c.valuation_score,"price_action":c.price_action_score,
                      "social":c.social_score,"sec":c.sec_score,"analyst":c.analyst_score}
        
        critical = [d for d,s in dim_scores.items() if dim_maxes[d] > 0 and s/dim_maxes[d] >= 0.6]
        elevated = [d for d,s in dim_scores.items() if dim_maxes[d] > 0 and 0.4 <= s/dim_maxes[d] < 0.6]
        
        dim_labels = {"news":"news sentiment","transcript":"earnings call language","insider":"insider selling",
                      "earnings":"earnings quality","short_interest":"short interest","valuation":"valuation",
                      "price_action":"price action","social":"social sentiment","sec":"SEC filings","analyst":"analyst activity"}
        
        if len(critical) >= 3:
            crit_names = ", ".join(dim_labels.get(d,d) for d in critical)
            opener = f"{c.ticker} ({c.company_name}) shows critical-level warning signals in {crit_names}. Multiple independent data sources are converging on a bearish thesis."
        elif len(critical) >= 2:
            crit_names = " and ".join(dim_labels.get(d,d) for d in critical)
            opener = f"{c.ticker} ({c.company_name}) has critical signals in {crit_names}, with corroborating evidence from additional sources."
        else:
            crit_name = dim_labels.get(critical[0], critical[0]) if critical else "multiple areas"
            opener = f"{c.ticker} ({c.company_name}) has a critical-level signal in {crit_name}."
            if elevated:
                elev_names = ", ".join(dim_labels.get(d,d) for d in elevated)
                opener += f" Supporting elevated signals in {elev_names}."
        
        sections = []
        dim_flag_map = [
            ("news", c.news_flags, c.news_score), ("transcript", c.transcript_flags, c.transcript_score),
            ("insider", c.insider_flags, c.insider_score), ("earnings", c.earnings_flags, c.earnings_score),
            ("short_interest", c.short_interest_flags, c.short_interest_score),
            ("valuation", c.valuation_flags, c.valuation_score), ("price_action", c.price_action_flags, c.price_action_score),
            ("social", c.social_flags, c.social_score),
            ("sec", c.sec_flags, c.sec_score), ("analyst", c.analyst_flags, c.analyst_score),
        ]
        section_labels = {"news":"NEWS","transcript":"EARNINGS CALL","insider":"INSIDERS","earnings":"EARNINGS",
                         "short_interest":"SHORT INTEREST","valuation":"VALUATION","price_action":"PRICE ACTION",
                         "social":"SOCIAL","sec":"SEC FILINGS","analyst":"ANALYSTS"}
        
        for dim, dim_flags, dim_score in dim_flag_map:
            if not dim_flags or dim_score == 0:
                continue
            max_val = dim_maxes.get(dim, 1)
            pct = dim_score / max_val if max_val > 0 else 0
            if pct < 0.4:
                continue
            
            tier = "🔥 CRITICAL" if pct >= 0.6 else "⚠️ ELEVATED"
            label = section_labels.get(dim, dim.upper())
            sections.append(f"{tier} — {label}: " + " ".join(dim_flags))
        
        thesis = opener + "\n\n" + "\n\n".join(sections)
        
        if c.risks:
            thesis += "\n\nRISKS TO SHORT: " + " ".join(c.risks)
        if c.catalyst:
            thesis += "\n\nCATALYST: " + c.catalyst
        
        return thesis
    
    # ── FULL SCAN ──
    
    def scan_ticker(self, ticker: str) -> Optional[Dict]:
        """Run full analysis on a single ticker."""
        try:
            # Get profile
            profile = self.fmp.get_profile(ticker)
            if not profile.get("price"):
                return None
            
            c = ShortCandidate(
                ticker=ticker,
                company_name=profile.get("companyName", ""),
                sector=profile.get("sector", ""),
                price=profile.get("price", 0),
                price_change_pct=profile.get("changesPercentage", 0),
                generated_at=datetime.utcnow().isoformat()
            )
            
            # Score each dimension — no sleeps between (FMP handles rate limiting)
            c.news_score, c.news_flags, c.top_headlines = self.score_news(ticker, c.company_name)
            
            # Skip transcript if no API Ninjas key (always returns 0)
            if self.apininjas:
                c.transcript_score, c.transcript_flags = self.score_transcript(ticker)
            else:
                c.transcript_score, c.transcript_flags = 0, []
            
            c.insider_score, c.insider_flags = self.score_insiders(ticker)
            c.earnings_score, c.earnings_flags = self.score_earnings(ticker)
            c.short_interest_score, c.short_interest_flags = self.score_short_interest(ticker)
            c.valuation_score, c.valuation_flags = self.score_valuation(ticker, profile)
            c.price_action_score, c.price_action_flags = self.score_price_action(ticker, c.price, profile)
            
            # Skip social if no meaningful source configured (always returns 0)
            c.social_score, c.social_flags, c.reddit_posts = 0, [], []
            
            c.sec_score, c.sec_flags = self.score_sec(ticker)
            c.analyst_score, c.analyst_flags = self.score_analysts(ticker, c.price)
            
            # Total
            c.total_score = (c.news_score + c.transcript_score + c.insider_score +
                            c.earnings_score + c.short_interest_score + c.valuation_score +
                            c.price_action_score + c.social_score + c.sec_score + c.analyst_score)
            
            # ── SIGNAL STRENGTH FILTERING ──
            dimension_maxes = {
                "news": 20, "transcript": 15, "insider": 15, "earnings": 15,
                "short_interest": 10, "valuation": 15, "price_action": 10,
                "social": 10, "sec": 10, "analyst": 5,
            }
            dimension_scores = {
                "news": c.news_score, "transcript": c.transcript_score,
                "insider": c.insider_score, "earnings": c.earnings_score,
                "short_interest": c.short_interest_score, "valuation": c.valuation_score,
                "price_action": c.price_action_score,
                "social": c.social_score, "sec": c.sec_score, "analyst": c.analyst_score,
            }
            
            critical_signals = []  # 60%+ of max
            elevated_signals = []  # 40%+ of max
            
            for dim, score_val in dimension_scores.items():
                max_val = dimension_maxes[dim]
                if max_val == 0:
                    continue
                pct = score_val / max_val
                if pct >= 0.6:
                    critical_signals.append(dim)
                elif pct >= 0.4:
                    elevated_signals.append(dim)
            
            # Log every ticker's scores for debugging
            score_summary = " | ".join(f"{d}:{s}" for d,s in dimension_scores.items() if s > 0)
            print(f"    Scores: {score_summary or '(all zero)'} | total={c.total_score}")
            print(f"    Critical: {critical_signals} | Elevated: {elevated_signals}")
            
            # Skip tickers with no signal at all
            if c.total_score == 0:
                print(f"  ✗ {ticker}: Filtered out — zero score")
                return None
            
            # Conviction based on signal strength
            if len(critical_signals) >= 3:
                c.conviction = "Very Strong"
            elif len(critical_signals) >= 2:
                c.conviction = "Strong"
            elif len(critical_signals) >= 1 and len(elevated_signals) >= 1:
                c.conviction = "Strong"
            elif len(critical_signals) >= 1:
                c.conviction = "Moderate"
            elif len(elevated_signals) >= 3:
                c.conviction = "Moderate"
            else:
                c.conviction = "Emerging"
            
            # Risks
            c.risks = self._assess_risks(c)
            
            # Catalyst
            if c.news_score >= 15:
                c.catalyst = "Negative news cycle is intensifying — next earnings or guidance update could accelerate decline."
            elif c.earnings_score >= 12:
                c.catalyst = "Deteriorating earnings trajectory — next quarterly report is the primary catalyst."
            elif c.insider_score >= 12:
                c.catalyst = "Insiders are selling aggressively — they often know before the market does."
            elif c.valuation_score >= 10:
                c.catalyst = "Extreme valuation leaves no margin for error — any earnings miss or guidance cut triggers repricing."
            elif c.price_action_score >= 7:
                c.catalyst = "Technical breakdown underway — momentum selling could accelerate as support levels fail."
            else:
                c.catalyst = "Monitor for continued deterioration across flagged areas over the next 30-60 days."
            
            # Generate thesis
            c.summary = self.generate_summary(c)
            
            print(f"  ✓ {ticker}: {len(critical_signals)} critical, {len(elevated_signals)} elevated ({c.conviction}) — {', '.join(critical_signals)}")
            return self._to_dict(c, critical_signals, elevated_signals)
            
        except Exception as e:
            print(f"  ✗ {ticker}: Error — {e}")
            return None
    
    def run_scan(self, max_deep: int = 75) -> Dict:
        """
        Two-pass scan:
        Pass 1: Sentiment screen — pull news for each ticker, score sentiment (fast)
        Pass 2: Deep scan — full 10-dimension analysis on tickers with negative sentiment
        """
        start = datetime.utcnow()
        
        print(f"\n{'='*60}")
        print(f"  ShortSight Scanner")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        # Get S&P 500
        print(f"\n  Loading S&P 500 universe...")
        universe = self.fmp.get_sp500_constituents()
        if not universe:
            universe = ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B","JPM",
                        "V","UNH","XOM","JNJ","WMT","PG","MA","HD","CVX","MRK","ABBV",
                        "PEP","KO","AVGO","COST","LLY","TMO","MCD","CSCO","ACN","ABT",
                        "DHR","NKE","TXN","PM","UPS","NEE","RTX","LOW","BMY","AMGN"]
        print(f"  Universe: {len(universe)} tickers")
        
        # ── PASS 1: SENTIMENT SCREEN ──
        # FMP news endpoint ignores symbol param — returns all recent news
        # Pull multiple pages to get broader ticker coverage
        print(f"\n  Pass 1: Building sentiment picture...")
        
        # Pull multiple pages of news
        all_news = []
        for page in range(20):  # 20 pages × 50 articles = 1000 articles
            batch = self.fmp._get("news/stock-latest", {"limit": "50", "page": str(page)})
            if not isinstance(batch, list) or not batch:
                print(f"  [News] Page {page}: empty — stopping pagination")
                break
            all_news.extend(batch)
            time.sleep(0.15)
        
        print(f"  [News] Fetched {len(all_news)} total articles")
        
        # Group articles by symbol
        universe_set = set(universe)
        news_by_ticker = {}
        for article in all_news:
            sym = (article.get("symbol","") or "").upper()
            if sym and sym in universe_set:
                if sym not in news_by_ticker:
                    news_by_ticker[sym] = []
                news_by_ticker[sym].append({
                    "title": article.get("title", ""),
                    "description": article.get("text", ""),
                    "source": {"name": article.get("site", "")},
                    "url": article.get("url", ""),
                    "publishedAt": article.get("publishedDate", "")
                })
        
        print(f"  [News] {len(news_by_ticker)} S&P tickers have news ({sum(len(v) for v in news_by_ticker.values())} articles matched)")
        
        # Also pull recent analyst downgrades as supplementary signal
        grades_data = self.fmp._get("grades", {"limit": "500"})
        downgrades_by_ticker = {}
        if isinstance(grades_data, list):
            for g in grades_data:
                sym = (g.get("symbol","") or "").upper()
                action = (g.get("action","") or "").lower()
                new_grade = (g.get("newGrade","") or "").lower()
                if sym in universe_set and ("downgrade" in action or any(x in new_grade for x in ["sell","underweight","underperform","reduce"])):
                    if sym not in downgrades_by_ticker:
                        downgrades_by_ticker[sym] = 0
                    downgrades_by_ticker[sym] += 1
            print(f"  [Grades] {len(downgrades_by_ticker)} tickers with recent downgrades")
        
        # Score sentiment for tickers with news
        sentiment_hits = []
        for ticker_sym, articles in news_by_ticker.items():
            result = self.sentiment.score_headlines(articles, ticker_sym)
            agg = result.get("aggregate_score", 0)
            bearish_ratio = result.get("bearish_ratio", 0)
            downgrades = downgrades_by_ticker.get(ticker_sym, 0)
            
            # Flag if negative sentiment OR multiple downgrades
            if agg <= -0.05 or bearish_ratio > 0.3 or downgrades >= 2:
                sentiment_hits.append({
                    "ticker": ticker_sym,
                    "sentiment_score": agg,
                    "bearish_ratio": bearish_ratio,
                    "article_count": result.get("article_count", 0),
                    "downgrades": downgrades,
                })
                print(f"  ★ {ticker_sym}: sentiment={agg:+.2f} bearish={bearish_ratio:.0%} articles={len(articles)} downgrades={downgrades}")
        
        # Add tickers with downgrades but no news
        for sym, count in downgrades_by_ticker.items():
            if count >= 2 and sym not in {h["ticker"] for h in sentiment_hits}:
                sentiment_hits.append({
                    "ticker": sym,
                    "sentiment_score": 0,
                    "bearish_ratio": 0,
                    "article_count": 0,
                    "downgrades": count,
                })
                print(f"  ★ {sym}: no news but {count} downgrades")
        
        pass1_time = (datetime.utcnow() - start).total_seconds()
        print(f"\n  Pass 1 complete in {pass1_time:.0f}s: {len(news_by_ticker)} tickers with news, {len(sentiment_hits)} flagged")
        
        # Sort by most negative sentiment first
        sentiment_hits.sort(key=lambda x: x["sentiment_score"])
        candidates = [h["ticker"] for h in sentiment_hits[:max_deep]]
        
        pass1_time = (datetime.utcnow() - start).total_seconds()
        print(f"\n  Pass 1 complete: {len(sentiment_hits)} with negative sentiment in {pass1_time:.0f}s")
        top_neg = ", ".join(f"{h['ticker']}({h['sentiment_score']:+.2f})" for h in sentiment_hits[:10])
        print(f"  Top negatives: {top_neg}")
        
        # ── PASS 2: DEEP SCAN ON SENTIMENT HITS ──
        print(f"\n  Pass 2: Deep analysis on {len(candidates)} tickers...")
        results = []
        for i, ticker in enumerate(candidates):
            if hasattr(self, '_progress_cb') and self._progress_cb:
                self._progress_cb(len(universe) + i + 1, len(universe) + len(candidates), ticker, len(results))
            
            print(f"  [{i+1}/{len(candidates)}] {ticker}")
            r = self.scan_ticker(ticker)
            if r:
                results.append(r)
            time.sleep(0.2)
        
        # Sort by critical signal count → elevated count → total score
        results.sort(key=lambda x: (
            x.get("critical_count", 0),
            x.get("elevated_count", 0),
            x.get("total_score", 0)
        ), reverse=True)
        
        elapsed = (datetime.utcnow() - start).total_seconds()
        
        output = {
            "candidates": results,
            "universe_size": len(universe),
            "sentiment_flagged": len(sentiment_hits),
            "screened": len(candidates),
            "found": len(results),
            "scan_seconds": round(elapsed, 1),
            "scanned_at": datetime.utcnow().isoformat(),
            "breakdown": {
                "very_strong": len([r for r in results if r["conviction"] == "Very Strong"]),
                "strong": len([r for r in results if r["conviction"] == "Strong"]),
                "moderate": len([r for r in results if r["conviction"] == "Moderate"]),
                "emerging": len([r for r in results if r["conviction"] == "Emerging"]),
            }
        }
        
        self._save(output)
        
        print(f"\n{'='*60}")
        print(f"  Scan complete! {len(results)} candidates found in {elapsed:.0f}s")
        print(f"  Pass 1: {len(universe)} screened → {len(sentiment_hits)} negative sentiment ({pass1_time:.0f}s)")
        print(f"  Pass 2: {len(candidates)} deep scanned → {len(results)} scored")
        bk = output["breakdown"]
        print(f"  Very Strong: {bk['very_strong']} | Strong: {bk['strong']} | Moderate: {bk['moderate']}")
        print(f"{'='*60}\n")
        
        return output
    
    def _quick_screen(self, universe: List[str], max_candidates: int = 75) -> List[str]:
        """Quick screen — tries FMP screener first (1 call), falls back to individual profiles."""
        universe_set = set(universe)
        candidates = []
        screened = 0
        
        # Strategy 1: Use FMP screener (single API call)
        print(f"  [Screen] Trying stock screener endpoint...")
        screener_data = self.fmp.get_stock_screener(market_cap_min=500_000_000, limit=1000)
        
        if screener_data:
            print(f"  [Screen] Screener returned {len(screener_data)} stocks")
            for p in screener_data:
                sym = p.get("symbol", "")
                if sym not in universe_set:
                    continue
                
                screened += 1
                pe = p.get("pe") or 0
                changes = p.get("changes") or p.get("changesPercentage") or 0
                mktCap = p.get("mktCap") or p.get("marketCap") or 0
                price = p.get("price") or p.get("lastPrice") or 0
                
                if not price or mktCap < 500_000_000:
                    continue
                
                if pe > 30 or pe < 0:
                    candidates.append(sym)
                elif changes < -0.5:
                    candidates.append(sym)
                elif pe > 15 and changes < 0:
                    candidates.append(sym)
                elif pe == 0:
                    candidates.append(sym)
            
            print(f"  [Screen] Screener: {screened} S&P matches, {len(candidates)} candidates")
            if candidates:
                return candidates[:max_candidates]
        
        # Strategy 2: Individual profile calls (slower but reliable)
        print(f"  [Screen] Screener didn't work — falling back to individual profiles...")
        candidates = []
        screened = 0
        no_data = 0
        
        for i, ticker in enumerate(universe):
            try:
                p = self.fmp.get_profile(ticker)
                
                if not p.get("price"):
                    no_data += 1
                    if no_data <= 3:
                        print(f"  [Screen] {ticker}: no price — keys: {list(p.keys())}")
                    continue
                
                screened += 1
                pe = p.get("pe") or 0
                changes = p.get("changes") or p.get("changesPercentage") or 0
                mktCap = p.get("mktCap") or 0
                
                if screened <= 2:
                    print(f"  [Screen] {ticker}: pe={pe}, changes={changes}, mktCap={mktCap}")
                
                if mktCap < 500_000_000:
                    continue
                
                if pe > 30 or pe < 0:
                    candidates.append(ticker)
                elif changes < -0.5:
                    candidates.append(ticker)
                elif pe > 15 and changes < 0:
                    candidates.append(ticker)
                elif pe == 0:
                    candidates.append(ticker)
                
            except Exception as e:
                print(f"  [Screen] Error on {ticker}: {e}")
            
            time.sleep(0.25)
            
            if (i + 1) % 100 == 0:
                print(f"  [Screen] Progress: {i+1}/{len(universe)}, {screened} with data, {len(candidates)} candidates")
            
            if len(candidates) >= max_candidates:
                break
        
        print(f"  [Screen] Done: {screened} screened, {no_data} no data, {len(candidates)} candidates")
        return candidates[:max_candidates]
    
    def _assess_risks(self, c: ShortCandidate) -> List[str]:
        risks = []
        if c.total_score >= 55:
            risks.append("May already be a crowded short — check short interest before entering.")
        if c.earnings_score < 10:
            risks.append("Earnings haven't fully collapsed — could beat lowered expectations.")
        risks.append("Short squeezes can cause violent reversals — use defined-risk options strategies (put spreads).")
        return risks
    
    def _to_dict(self, c: ShortCandidate, critical: List[str] = None, elevated: List[str] = None) -> Dict:
        dim_labels = {
            "news": "News Sentiment", "transcript": "Earnings Call",
            "insider": "Insider Selling", "earnings": "Earnings Quality",
            "short_interest": "Short Interest", "valuation": "Valuation",
            "price_action": "Price Action",
            "social": "Social Sentiment", "sec": "SEC Filings", "analyst": "Analyst Downgrades",
        }
        dim_maxes = {
            "news": 20, "transcript": 15, "insider": 15, "earnings": 15,
            "short_interest": 10, "valuation": 15, "price_action": 10,
            "social": 10, "sec": 10, "analyst": 5,
        }
        dim_scores = {
            "news": c.news_score, "transcript": c.transcript_score,
            "insider": c.insider_score, "earnings": c.earnings_score,
            "short_interest": c.short_interest_score, "valuation": c.valuation_score,
            "price_action": c.price_action_score,
            "social": c.social_score, "sec": c.sec_score, "analyst": c.analyst_score,
        }
        
        # Build signal strength list for display
        signals = []
        for dim in (critical or []):
            signals.append({
                "dimension": dim, "label": dim_labels.get(dim, dim),
                "tier": "critical", "score": dim_scores.get(dim, 0),
                "max": dim_maxes.get(dim, 0),
                "pct": round(dim_scores.get(dim, 0) / max(dim_maxes.get(dim, 1), 1) * 100),
            })
        for dim in (elevated or []):
            signals.append({
                "dimension": dim, "label": dim_labels.get(dim, dim),
                "tier": "elevated", "score": dim_scores.get(dim, 0),
                "max": dim_maxes.get(dim, 0),
                "pct": round(dim_scores.get(dim, 0) / max(dim_maxes.get(dim, 1), 1) * 100),
            })
        
        return {
            "ticker": c.ticker,
            "company_name": c.company_name,
            "sector": c.sector,
            "price": c.price,
            "price_change_pct": c.price_change_pct,
            "total_score": c.total_score,
            "conviction": c.conviction,
            "critical_count": len(critical or []),
            "elevated_count": len(elevated or []),
            "signals": signals,
            "scores": {
                "news": c.news_score,
                "transcript": c.transcript_score,
                "insider": c.insider_score,
                "earnings": c.earnings_score,
                "short_interest": c.short_interest_score,
                "valuation": c.valuation_score,
                "price_action": c.price_action_score,
                "social": c.social_score,
                "sec": c.sec_score,
                "analyst": c.analyst_score,
            },
            "flags": {
                "news": c.news_flags,
                "transcript": c.transcript_flags,
                "insider": c.insider_flags,
                "earnings": c.earnings_flags,
                "short_interest": c.short_interest_flags,
                "valuation": c.valuation_flags,
                "price_action": c.price_action_flags,
                "social": c.social_flags,
                "sec": c.sec_flags,
                "analyst": c.analyst_flags,
            },
            "top_headlines": c.top_headlines,
            "reddit_posts": c.reddit_posts[:3],
            "summary": c.summary,
            "risks": c.risks,
            "catalyst": c.catalyst,
            "generated_at": c.generated_at,
        }
    
    def _save(self, data: Dict):
        os.makedirs(os.path.dirname(self.results_file), exist_ok=True)
        with open(self.results_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
    
    def get_cached(self) -> Dict:
        try:
            with open(self.results_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"candidates": [], "found": 0, "scanned_at": None}

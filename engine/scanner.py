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
from engine.fetchers import NewsFetcher, FMPFetcher, RedditFetcher, SECFetcher, UnusualWhalesFetcher, QuiverFetcher, StocktwitsFetcher


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
    congress_score: int = 0
    options_flow_score: int = 0
    social_score: int = 0
    sec_score: int = 0
    analyst_score: int = 0
    
    news_flags: List[str] = field(default_factory=list)
    transcript_flags: List[str] = field(default_factory=list)
    insider_flags: List[str] = field(default_factory=list)
    earnings_flags: List[str] = field(default_factory=list)
    short_interest_flags: List[str] = field(default_factory=list)
    congress_flags: List[str] = field(default_factory=list)
    options_flow_flags: List[str] = field(default_factory=list)
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
    
    def __init__(self, news_key: str, fmp_key: str, uw_key: str = "", quiver_key: str = ""):
        self.news = NewsFetcher(news_key)
        self.fmp = FMPFetcher(fmp_key)
        self.reddit = RedditFetcher()
        self.sec = SECFetcher()
        self.sentiment = SentimentEngine()
        self.stocktwits = StocktwitsFetcher()
        
        # Optional paid sources
        self.uw = UnusualWhalesFetcher(uw_key) if uw_key else None
        self.quiver = QuiverFetcher(quiver_key) if quiver_key else None
        
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
            fmp_news = self.fmp.get_stock_news(ticker)
            for item in (fmp_news or []):
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
            transcript = self.fmp.get_earnings_transcript(ticker)
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
                if any(t in (name + " " + title) for t in csuite_titles):
                    csuite_sells += 1
                    csuite_value += value
            elif any(t in tx for t in ["purchase", "buy", "p-purchase"]):
                total_bought += value
        
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
        
        # Earnings surprises
        surprises = self.fmp.get_earnings_surprises(ticker)
        if surprises:
            misses = 0
            for q in surprises[:4]:
                actual = q.get("actualEarningResult") or q.get("eps")
                est = q.get("estimatedEarning") or q.get("epsEstimated")
                if actual is not None and est is not None and est != 0:
                    surprise = ((actual - est) / abs(est)) * 100
                    if surprise < -2:
                        misses += 1
            
            if misses >= 3:
                score += 12
                flags.append(f"Missed EPS in {misses}/4 recent quarters — chronic underperformance")
            elif misses >= 2:
                score += 8
                flags.append(f"Missed EPS in {misses}/4 recent quarters")
            elif misses >= 1:
                score += 4
                flags.append(f"Missed EPS in most recent quarter")
        
        # Income statement trends
        stmts = self.fmp.get_income_statements(ticker)
        if stmts and len(stmts) >= 3:
            revenues = [s.get("revenue", 0) or 0 for s in stmts[:4]]
            margins = []
            for s in stmts[:4]:
                rev = s.get("revenue", 0) or 0
                gp = s.get("grossProfit", 0) or 0
                if rev > 0:
                    margins.append(round((gp / rev) * 100, 1))
            
            # Revenue deceleration
            if len(revenues) >= 2 and revenues[1] > 0:
                growth = ((revenues[0] - revenues[1]) / abs(revenues[1])) * 100
                if growth < -5:
                    score += 5
                    flags.append(f"Revenue contracting {growth:.1f}% QoQ")
                elif growth < 0:
                    score += 3
                    flags.append(f"Revenue declining {growth:.1f}% QoQ")
            
            # Margin compression
            if len(margins) >= 2 and margins[-1] > margins[0] + 3:
                score += 4
                flags.append(f"Gross margins compressing: {margins[-1]:.1f}% → {margins[0]:.1f}%")
        
        # Estimate revisions
        estimates = self.fmp.get_analyst_estimates(ticker)
        if isinstance(estimates, list) and len(estimates) >= 2:
            curr = estimates[0].get("estimatedEpsAvg")
            prev = estimates[1].get("estimatedEpsAvg")
            if curr and prev and prev != 0:
                rev_pct = ((curr - prev) / abs(prev)) * 100
                if rev_pct < -10:
                    score += 4
                    flags.append(f"EPS estimates cut {abs(rev_pct):.0f}%")
                elif rev_pct < -5:
                    score += 2
                    flags.append(f"EPS estimates revised down {abs(rev_pct):.0f}%")
        
        return min(score, 15), flags
    
    # ── SHORT INTEREST (10 pts) ──
    
    def score_short_interest(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        try:
            data = self.fmp.get_share_float(ticker)
            if not data:
                return 0, []
            
            short_pct = data.get("shortPercentOfSharesOutstanding") or data.get("shortPercentFloat") or 0
            short_ratio = data.get("shortRatio") or data.get("daysToCover") or 0
            
            # Normalize — some APIs return as decimal, some as percentage
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
    
    # ── CONGRESSIONAL TRADING (10 pts) ──
    
    def score_congress(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        try:
            # Check Senate trades
            senate = self.fmp.get_senate_trades(ticker)
            house = self.fmp.get_house_trades(ticker)
            
            sells = []
            cutoff = datetime.utcnow() - timedelta(days=90)
            
            for trade in (senate or []) + (house or []):
                tx_type = (trade.get("type", "") or trade.get("transactionType", "") or "").lower()
                trade_date_str = (trade.get("transactionDate", "") or trade.get("disclosureDate", ""))[:10]
                
                try:
                    if trade_date_str:
                        td = datetime.strptime(trade_date_str, "%Y-%m-%d")
                        if td < cutoff:
                            continue
                except (ValueError, TypeError):
                    continue
                
                if any(s in tx_type for s in ["sale", "sell", "sold"]):
                    name = trade.get("representative", "") or trade.get("senator", "") or trade.get("name", "")
                    amount = trade.get("amount", "") or trade.get("estimatedAmount", "")
                    chamber = "Senate" if trade in (senate or []) else "House"
                    sells.append({
                        "name": name,
                        "amount": amount,
                        "date": trade_date_str,
                        "chamber": chamber,
                    })
            
            if len(sells) >= 3:
                score += 8
                names = list(set(s["name"] for s in sells if s["name"]))[:3]
                flags.append(f"{len(sells)} congressional sell transactions — {', '.join(names)}")
            elif len(sells) >= 1:
                score += 4
                s = sells[0]
                flags.append(f"{s['chamber']} member {s['name']} sold {s['amount']} on {s['date']}")
        except Exception as e:
            print(f"  [Congress] Error for {ticker}: {e}")
        
        return min(score, 10), flags
    
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
    
    # ── OPTIONS FLOW (10 pts) — Unusual Whales ──
    
    def score_options_flow(self, ticker: str) -> Tuple[int, List[str]]:
        score = 0
        flags = []
        
        if not self.uw:
            return 0, []
        
        try:
            summary = self.uw.get_ticker_options_summary(ticker)
            if not summary or summary.get("total_trades", 0) < 5:
                return 0, []
            
            pc_ratio = summary.get("put_call_ratio", 1.0)
            put_pct = summary.get("put_pct", 50)
            large_puts = summary.get("large_put_trades", 0)
            net_premium = summary.get("net_premium", 0)
            
            # High put/call ratio
            if pc_ratio > 2.0:
                score += 4
                flags.append(f"Put/call ratio {pc_ratio:.1f}x — heavy put buying ({put_pct:.0f}% puts)")
            elif pc_ratio > 1.5:
                score += 2
                flags.append(f"Elevated put/call ratio: {pc_ratio:.1f}x")
            
            # Large put trades (institutional bearish bets)
            if large_puts >= 5:
                score += 4
                flags.append(f"{large_puts} large put trades (>$100K premium) — institutional bearish positioning")
            elif large_puts >= 2:
                score += 2
                flags.append(f"{large_puts} large put trades detected")
            
            # Negative net premium (more money in puts than calls)
            if net_premium < -500_000:
                score += 3
                flags.append(f"Net premium: ${net_premium/1e6:.1f}M — significantly more premium in puts")
            elif net_premium < -100_000:
                score += 1
                flags.append(f"Net premium skewing bearish: ${net_premium/1e3:.0f}K")
            
        except Exception as e:
            print(f"  [OptionsFlow] Error for {ticker}: {e}")
        
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
                    score += 4
                    flags.append(f"{bearish_pct:.0%} of analysts rate Sell — unusual bearish consensus")
                elif bearish_pct > 0.15:
                    score += 2
                    flags.append(f"{bearish_pct:.0%} analyst sell ratings")
        
        # Price target vs current price
        pt = self.fmp.get_price_target_consensus(ticker)
        if pt and price > 0:
            consensus = pt.get("targetConsensus") or pt.get("targetPrice", 0)
            if consensus and consensus > 0:
                upside = ((consensus - price) / price) * 100
                if upside < -10:
                    score += 4
                    flags.append(f"Trading {abs(upside):.0f}% ABOVE consensus target (${consensus:.0f}) — priced beyond expectations")
                elif upside < 0:
                    score += 2
                    flags.append(f"Above consensus price target (${consensus:.0f})")
        
        # Recent grades (downgrades)
        grades = self.fmp.get_grades(ticker)
        downgrades = 0
        for g in (grades or [])[:10]:
            action = (g.get("newGrade", "") or "").lower()
            if any(x in action for x in ["sell", "underweight", "underperform", "reduce"]):
                downgrades += 1
        
        if downgrades >= 3:
            score += 3
            flags.append(f"{downgrades} recent analyst downgrades")
        elif downgrades >= 1:
            score += 1
            flags.append(f"Recent analyst downgrade(s)")
        
        return min(score, 5), flags
    
    # ── THESIS GENERATOR ──
    
    def generate_summary(self, c: ShortCandidate) -> str:
        """Generate plain-English short thesis focused on strongest signals."""
        # Count strong dimensions
        dim_maxes = {"news":20,"transcript":15,"insider":15,"earnings":15,"short_interest":10,"congress":10,"options_flow":10,"social":10,"sec":10,"analyst":5}
        dim_scores = {"news":c.news_score,"transcript":c.transcript_score,"insider":c.insider_score,"earnings":c.earnings_score,
                      "short_interest":c.short_interest_score,"congress":c.congress_score,"options_flow":c.options_flow_score,
                      "social":c.social_score,"sec":c.sec_score,"analyst":c.analyst_score}
        
        critical = [d for d,s in dim_scores.items() if dim_maxes[d] > 0 and s/dim_maxes[d] >= 0.8]
        elevated = [d for d,s in dim_scores.items() if dim_maxes[d] > 0 and 0.6 <= s/dim_maxes[d] < 0.8]
        
        dim_labels = {"news":"news sentiment","transcript":"earnings call language","insider":"insider selling",
                      "earnings":"earnings quality","short_interest":"short interest","congress":"congressional trading",
                      "options_flow":"options flow","social":"social sentiment","sec":"SEC filings","analyst":"analyst activity"}
        
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
        
        # Only include sections with meaningful scores
        sections = []
        dim_flag_map = [
            ("news", c.news_flags, c.news_score), ("transcript", c.transcript_flags, c.transcript_score),
            ("insider", c.insider_flags, c.insider_score), ("earnings", c.earnings_flags, c.earnings_score),
            ("short_interest", c.short_interest_flags, c.short_interest_score),
            ("congress", c.congress_flags, c.congress_score), ("options_flow", c.options_flow_flags, c.options_flow_score),
            ("social", c.social_flags, c.social_score),
            ("sec", c.sec_flags, c.sec_score), ("analyst", c.analyst_flags, c.analyst_score),
        ]
        section_labels = {"news":"NEWS","transcript":"EARNINGS CALL","insider":"INSIDERS","earnings":"EARNINGS",
                         "short_interest":"SHORT INTEREST","congress":"CONGRESSIONAL TRADING","options_flow":"OPTIONS FLOW",
                         "social":"SOCIAL","sec":"SEC FILINGS","analyst":"ANALYSTS"}
        
        for dim, dim_flags, dim_score in dim_flag_map:
            if not dim_flags or dim_score == 0:
                continue
            max_val = dim_maxes.get(dim, 1)
            pct = dim_score / max_val if max_val > 0 else 0
            if pct < 0.6:
                continue  # Only show elevated+ signals in thesis
            
            tier = "🔥 CRITICAL" if pct >= 0.8 else "⚠️ ELEVATED"
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
            
            time.sleep(0.2)
            
            # Score each dimension
            c.news_score, c.news_flags, c.top_headlines = self.score_news(ticker, c.company_name)
            time.sleep(0.3)
            
            c.transcript_score, c.transcript_flags = self.score_transcript(ticker)
            time.sleep(0.3)
            
            c.insider_score, c.insider_flags = self.score_insiders(ticker)
            time.sleep(0.2)
            
            c.earnings_score, c.earnings_flags = self.score_earnings(ticker)
            time.sleep(0.3)
            
            c.short_interest_score, c.short_interest_flags = self.score_short_interest(ticker)
            time.sleep(0.2)
            
            c.congress_score, c.congress_flags = self.score_congress(ticker)
            time.sleep(0.2)
            
            c.options_flow_score, c.options_flow_flags = self.score_options_flow(ticker)
            time.sleep(0.2)
            
            c.social_score, c.social_flags, c.reddit_posts = self.score_social(ticker)
            time.sleep(0.2)
            
            c.sec_score, c.sec_flags = self.score_sec(ticker)
            time.sleep(0.1)
            
            c.analyst_score, c.analyst_flags = self.score_analysts(ticker, c.price)
            
            # Total (still useful for secondary ranking)
            c.total_score = (c.news_score + c.transcript_score + c.insider_score +
                            c.earnings_score + c.short_interest_score + c.congress_score +
                            c.options_flow_score + c.social_score + c.sec_score + c.analyst_score)
            
            # ── SIGNAL STRENGTH FILTERING ──
            # Only surface stocks with at least 1 "critical" signal (80%+ of dimension max)
            dimension_maxes = {
                "news": 20, "transcript": 15, "insider": 15, "earnings": 15,
                "short_interest": 10, "congress": 10, "options_flow": 10,
                "social": 10, "sec": 10, "analyst": 5,
            }
            dimension_scores = {
                "news": c.news_score, "transcript": c.transcript_score,
                "insider": c.insider_score, "earnings": c.earnings_score,
                "short_interest": c.short_interest_score, "congress": c.congress_score,
                "options_flow": c.options_flow_score,
                "social": c.social_score, "sec": c.sec_score, "analyst": c.analyst_score,
            }
            
            critical_signals = []  # 80%+ of max
            elevated_signals = []  # 60%+ of max
            
            for dim, score_val in dimension_scores.items():
                max_val = dimension_maxes[dim]
                if max_val == 0:
                    continue
                pct = score_val / max_val
                if pct >= 0.8:
                    critical_signals.append(dim)
                elif pct >= 0.6:
                    elevated_signals.append(dim)
            
            # FILTER: Must have at least 1 critical signal
            if not critical_signals:
                return None
            
            # Conviction based on signal strength, not total score
            if len(critical_signals) >= 3:
                c.conviction = "Very Strong"
            elif len(critical_signals) >= 2:
                c.conviction = "Strong"
            elif len(critical_signals) >= 1 and len(elevated_signals) >= 2:
                c.conviction = "Strong"
            elif len(critical_signals) >= 1 and len(elevated_signals) >= 1:
                c.conviction = "Moderate"
            else:
                c.conviction = "Moderate"
            
            # Risks
            c.risks = self._assess_risks(c)
            
            # Catalyst
            if c.news_score >= 15:
                c.catalyst = "Negative news cycle is intensifying — next earnings or guidance update could accelerate decline."
            elif c.earnings_score >= 12:
                c.catalyst = "Deteriorating earnings trajectory — next quarterly report is the primary catalyst."
            elif c.insider_score >= 12:
                c.catalyst = "Insiders are selling aggressively — they often know before the market does."
            else:
                c.catalyst = "Monitor for continued deterioration across flagged areas over the next 30-60 days."
            
            # Generate thesis
            c.summary = self.generate_summary(c)
            
            print(f"  ✓ {ticker}: {len(critical_signals)} critical, {len(elevated_signals)} elevated ({c.conviction}) — {', '.join(critical_signals)}")
            return self._to_dict(c, critical_signals, elevated_signals)
            
        except Exception as e:
            print(f"  ✗ {ticker}: Error — {e}")
            return None
    
    def run_scan(self, max_deep: int = 30) -> Dict:
        """
        Full scan: quick screen S&P 500, then deep analysis on candidates.
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
            # Fallback
            universe = ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B","JPM",
                        "V","UNH","XOM","JNJ","WMT","PG","MA","HD","CVX","MRK","ABBV",
                        "PEP","KO","AVGO","COST","LLY","TMO","MCD","CSCO","ACN","ABT",
                        "DHR","NKE","TXN","PM","UPS","NEE","RTX","LOW","BMY","AMGN"]
        print(f"  Universe: {len(universe)} tickers")
        
        # Quick screen via batch profiles
        print(f"\n  Pass 1: Quick screening...")
        candidates = self._quick_screen(universe, max_deep)
        print(f"  Found {len(candidates)} candidates for deep analysis\n")
        
        # Deep scan
        print(f"  Pass 2: Deep analysis...")
        results = []
        for i, ticker in enumerate(candidates):
            print(f"  [{i+1}/{len(candidates)}] {ticker}")
            r = self.scan_ticker(ticker)
            if r:
                results.append(r)
            time.sleep(0.3)
        
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
            "screened": len(candidates),
            "found": len(results),
            "scan_seconds": round(elapsed, 1),
            "scanned_at": datetime.utcnow().isoformat(),
            "breakdown": {
                "very_strong": len([r for r in results if r["conviction"] == "Very Strong"]),
                "strong": len([r for r in results if r["conviction"] == "Strong"]),
                "moderate": len([r for r in results if r["conviction"] == "Moderate"]),
                "weak": len([r for r in results if r["conviction"] == "Weak"]),
            }
        }
        
        self._save(output)
        
        print(f"\n{'='*60}")
        print(f"  Scan complete! {len(results)} candidates found in {elapsed:.0f}s")
        bk = output["breakdown"]
        print(f"  Very Strong: {bk['very_strong']} | Strong: {bk['strong']} | Moderate: {bk['moderate']}")
        print(f"{'='*60}\n")
        
        return output
    
    def _quick_screen(self, universe: List[str], max_candidates: int = 30) -> List[str]:
        """Quick screen using batch profiles to find weak stocks."""
        candidates = []
        batch_size = 20
        
        for i in range(0, len(universe), batch_size):
            batch = universe[i:i+batch_size]
            try:
                profiles = self.fmp.get_batch_profiles(batch)
                for p in profiles:
                    sym = p.get("symbol", "")
                    pe = p.get("pe") or 0
                    changes = p.get("changes") or 0
                    mktCap = p.get("mktCap") or 0
                    
                    if mktCap < 2_000_000_000:
                        continue
                    
                    # Flag for deeper analysis
                    if pe > 50 or pe < 0:
                        candidates.append(sym)
                    elif changes < -2:
                        candidates.append(sym)
                    elif pe > 30 and changes < 0:
                        candidates.append(sym)
                
                time.sleep(0.3)
            except Exception as e:
                print(f"  [Screen] Batch error: {e}")
            
            if len(candidates) >= max_candidates * 2:
                break
        
        # Deduplicate
        seen = set()
        unique = []
        for t in candidates:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        
        return unique[:max_candidates]
    
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
            "short_interest": "Short Interest", "congress": "Congressional Trades",
            "options_flow": "Options Flow",
            "social": "Social Sentiment", "sec": "SEC Filings", "analyst": "Analyst Downgrades",
        }
        dim_maxes = {
            "news": 20, "transcript": 15, "insider": 15, "earnings": 15,
            "short_interest": 10, "congress": 10, "options_flow": 10,
            "social": 10, "sec": 10, "analyst": 5,
        }
        dim_scores = {
            "news": c.news_score, "transcript": c.transcript_score,
            "insider": c.insider_score, "earnings": c.earnings_score,
            "short_interest": c.short_interest_score, "congress": c.congress_score,
            "options_flow": c.options_flow_score,
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
                "congress": c.congress_score,
                "options_flow": c.options_flow_score,
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
                "congress": c.congress_flags,
                "options_flow": c.options_flow_flags,
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

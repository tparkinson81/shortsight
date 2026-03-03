"""
ShortSight — Sentiment Analysis Engine
Scores news headlines and text for bearish/bullish sentiment
using keyword analysis, phrase detection, and contextual scoring.
"""

import re
from typing import Dict, List, Tuple


class SentimentEngine:
    """Analyzes text sentiment with a focus on detecting bearish signals."""
    
    # Bearish phrases and their weights (negative = bearish)
    BEARISH_SIGNALS = {
        # Earnings & guidance
        "misses estimates": -0.8, "missed expectations": -0.8, "missed estimates": -0.8,
        "below expectations": -0.6, "disappointing results": -0.7, "disappointing earnings": -0.7,
        "guidance cut": -0.9, "lowers guidance": -0.9, "lowered outlook": -0.8,
        "cuts forecast": -0.8, "reduces guidance": -0.8, "warns on earnings": -0.8,
        "profit warning": -0.9, "revenue shortfall": -0.7, "revenue miss": -0.7,
        "earnings miss": -0.8, "weaker than expected": -0.6,
        
        # Accounting & governance
        "restates": -0.9, "restatement": -0.9, "accounting irregularities": -1.0,
        "material weakness": -0.9, "sec investigation": -1.0, "sec probe": -1.0,
        "sec charges": -1.0, "audit concern": -0.8, "delayed filing": -0.8,
        "going concern": -1.0, "fraud": -1.0, "misleading": -0.8,
        "whistleblower": -0.8, "class action": -0.7, "lawsuit": -0.5,
        "regulatory action": -0.7, "fined": -0.6, "penalty": -0.6,
        
        # Executive & personnel
        "ceo departs": -0.8, "ceo resigns": -0.8, "ceo fired": -0.9,
        "cfo leaves": -0.8, "cfo resigns": -0.8, "executive departure": -0.7,
        "leadership change": -0.5, "board shakeup": -0.6, "management turmoil": -0.7,
        "mass layoffs": -0.7, "major layoffs": -0.7, "workforce reduction": -0.6,
        "job cuts": -0.5, "restructuring": -0.4,
        
        # Business deterioration
        "losing market share": -0.7, "competitive pressure": -0.5,
        "customer loss": -0.7, "contract loss": -0.7, "lost contract": -0.7,
        "demand weakness": -0.6, "slowing growth": -0.5, "growth stalls": -0.6,
        "declining revenue": -0.7, "revenue decline": -0.7, "sales decline": -0.7,
        "margin pressure": -0.5, "margin compression": -0.6,
        "cash burn": -0.7, "liquidity concerns": -0.8, "debt concerns": -0.7,
        "credit downgrade": -0.8, "covenant violation": -0.9,
        "bankruptcy": -1.0, "chapter 11": -1.0, "default": -0.9,
        
        # Market & analyst
        "downgrades": -0.5, "downgraded": -0.5, "price target cut": -0.6,
        "price target lowered": -0.6, "sell rating": -0.6, "underperform": -0.5,
        "overvalued": -0.5, "bubble": -0.6, "short seller": -0.4,
        "bear case": -0.4, "risks mount": -0.5, "red flag": -0.6,
        
        # Product & operations
        "product recall": -0.7, "safety concern": -0.6, "data breach": -0.7,
        "supply chain disruption": -0.5, "production halt": -0.6,
        "fda rejection": -0.9, "clinical trial failure": -0.9,
        "patent loss": -0.6, "patent expired": -0.5,
    }
    
    BULLISH_SIGNALS = {
        "beats estimates": 0.7, "beat expectations": 0.7, "above expectations": 0.6,
        "raises guidance": 0.8, "record revenue": 0.7, "record earnings": 0.7,
        "strong results": 0.6, "upgraded": 0.5, "price target raised": 0.5,
        "new contract": 0.5, "partnership": 0.4, "acquisition": 0.3,
        "fda approval": 0.8, "breakthrough": 0.5, "innovation": 0.3,
        "buyback": 0.4, "dividend increase": 0.5, "insider buying": 0.6,
    }
    
    # Red flag words that amplify bearish sentiment
    AMPLIFIERS = {
        "significant": 1.3, "major": 1.3, "severe": 1.4, "critical": 1.4,
        "unprecedented": 1.3, "shocking": 1.3, "dramatic": 1.2,
        "plunge": 1.3, "crash": 1.4, "collapse": 1.4, "plummet": 1.3,
        "tumble": 1.2, "tank": 1.2, "dive": 1.2, "slide": 1.1,
        "surge": 1.2, "spike": 1.2, "soar": 1.2, "rally": 1.1,
    }
    
    def score_text(self, text: str) -> Dict:
        """
        Score a piece of text for sentiment.
        Returns: {score: float (-1 to 1), signals: list, label: str}
        """
        if not text:
            return {"score": 0, "signals": [], "label": "neutral"}
        
        text_lower = text.lower()
        signals = []
        total_score = 0
        
        # Check bearish phrases
        for phrase, weight in self.BEARISH_SIGNALS.items():
            if phrase in text_lower:
                # Check for amplifiers nearby
                amplifier = 1.0
                for amp_word, amp_mult in self.AMPLIFIERS.items():
                    if amp_word in text_lower:
                        amplifier = max(amplifier, amp_mult)
                
                adjusted = weight * amplifier
                total_score += adjusted
                signals.append({"phrase": phrase, "score": round(adjusted, 2), "type": "bearish"})
        
        # Check bullish phrases
        for phrase, weight in self.BULLISH_SIGNALS.items():
            if phrase in text_lower:
                total_score += weight
                signals.append({"phrase": phrase, "score": round(weight, 2), "type": "bullish"})
        
        # Normalize to -1 to 1 range
        if total_score > 0:
            normalized = min(total_score / 2.0, 1.0)
        elif total_score < 0:
            normalized = max(total_score / 2.0, -1.0)
        else:
            normalized = 0
        
        # Label
        if normalized <= -0.5:
            label = "very_bearish"
        elif normalized <= -0.2:
            label = "bearish"
        elif normalized >= 0.5:
            label = "very_bullish"
        elif normalized >= 0.2:
            label = "bullish"
        else:
            label = "neutral"
        
        return {
            "score": round(normalized, 3),
            "raw_score": round(total_score, 3),
            "signals": sorted(signals, key=lambda x: x["score"]),
            "label": label
        }
    
    def score_transcript(self, transcript: str) -> Dict:
        """
        Analyze an earnings call transcript for red flags.
        Looks for: deflection, hedging, buzzword overuse, contradictions.
        """
        if not transcript or len(transcript) < 200:
            return {"score": 0, "flags": [], "hedging_ratio": 0, "buzzword_ratio": 0}
        
        text = transcript.lower()
        word_count = len(text.split())
        flags = []
        score = 0  # negative = bearish
        
        # Hedging & deflection phrases
        hedging = [
            "going forward", "we believe", "we expect", "we anticipate",
            "headwinds", "challenging environment", "macro uncertainty",
            "as we navigate", "strategic pivot", "right-sizing",
            "one-time", "non-recurring", "adjusted basis",
            "excluding items", "on a normalized basis",
            "we remain confident", "we are cautiously optimistic",
            "it's too early to say", "we're not in a position to",
            "we'll get back to you on that", "that's a great question",
        ]
        hedge_count = sum(1 for h in hedging if h in text)
        hedge_ratio = hedge_count / max(word_count / 500, 1)
        
        if hedge_ratio > 3:
            score -= 0.6
            flags.append(f"Heavy hedging language ({hedge_count} deflection phrases) — executives avoiding direct answers")
        elif hedge_ratio > 1.5:
            score -= 0.3
            flags.append(f"Elevated hedging language ({hedge_count} phrases)")
        
        # Buzzword overuse (substance vs hype)
        buzzwords = [
            "transformational", "revolutionary", "game-changing", "paradigm shift",
            "synergy", "best-in-class", "world-class", "cutting-edge",
            "disruptive", "innovative", "unprecedented opportunity",
            "unlock value", "shareholder value", "optimize",
            "AI", "artificial intelligence", "machine learning",
        ]
        buzz_count = sum(1 for b in buzzwords if b in text)
        buzz_ratio = buzz_count / max(word_count / 1000, 1)
        
        if buzz_ratio > 4:
            score -= 0.4
            flags.append(f"Excessive buzzword usage ({buzz_count} instances) — watch for substance vs hype")
        elif buzz_ratio > 2:
            score -= 0.2
            flags.append(f"Above-average promotional language ({buzz_count} buzzwords)")
        
        # Negative business signals in transcript
        negative_signals = {
            "restructuring plan": -0.3,
            "workforce reduction": -0.3,
            "impairment charge": -0.4,
            "goodwill write": -0.4,
            "going concern": -0.8,
            "covenant": -0.3,
            "restatement": -0.6,
            "material weakness": -0.5,
            "delayed filing": -0.4,
            "liquidity position": -0.2,
            "cash preservation": -0.3,
            "cost reduction": -0.2,
            "deceleration": -0.3,
            "competitive pressure": -0.2,
            "market share loss": -0.4,
            "customer churn": -0.3,
            "guidance revision": -0.3,
            "lower our expectations": -0.4,
            "below our target": -0.3,
        }
        
        for phrase, weight in negative_signals.items():
            if phrase in text:
                score += weight
                flags.append(f"Transcript red flag: \"{phrase}\"")
        
        # Normalize
        normalized = max(min(score, 0), -1.0)
        
        return {
            "score": round(normalized, 3),
            "flags": flags,
            "hedging_ratio": round(hedge_ratio, 2),
            "buzzword_ratio": round(buzz_ratio, 2),
            "hedge_count": hedge_count,
            "buzz_count": buzz_count,
        }
    
    def score_headlines(self, articles: List[Dict], ticker: str = "") -> Dict:
        """
        Score a batch of news articles.
        Returns aggregate sentiment + individual scores.
        """
        if not articles:
            return {
                "aggregate_score": 0,
                "label": "neutral",
                "article_count": 0,
                "bearish_count": 0,
                "bullish_count": 0,
                "articles": []
            }
        
        scored_articles = []
        total = 0
        bearish = 0
        bullish = 0
        
        for article in articles:
            title = article.get("title", "") or ""
            desc = article.get("description", "") or ""
            text = title + " " + desc
            
            result = self.score_text(text)
            
            scored_articles.append({
                "title": title[:150],
                "source": article.get("source", {}).get("name", "") if isinstance(article.get("source"), dict) else str(article.get("source", "")),
                "url": article.get("url", ""),
                "published": article.get("publishedAt", "") or article.get("date", ""),
                "sentiment": result
            })
            
            total += result["score"]
            if result["score"] < -0.15:
                bearish += 1
            elif result["score"] > 0.15:
                bullish += 1
        
        count = len(scored_articles)
        avg = total / count if count > 0 else 0
        
        # Bearish ratio is important
        bearish_ratio = bearish / count if count > 0 else 0
        
        if avg <= -0.3 or bearish_ratio > 0.6:
            label = "very_bearish"
        elif avg <= -0.1 or bearish_ratio > 0.4:
            label = "bearish"
        elif avg >= 0.3:
            label = "very_bullish"
        elif avg >= 0.1:
            label = "bullish"
        else:
            label = "neutral"
        
        return {
            "aggregate_score": round(avg, 3),
            "label": label,
            "article_count": count,
            "bearish_count": bearish,
            "bullish_count": bullish,
            "bearish_ratio": round(bearish_ratio, 2),
            "articles": sorted(scored_articles, key=lambda x: x["sentiment"]["score"])
        }

from flask import Flask, render_template, jsonify
import requests
import xgboost as xgb
import pandas as pd
import feedparser
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Load the trained XGBoost model once at startup
model = xgb.XGBRegressor()
model.load_model("xgb_model.json")

NEGATIVE_TERMS = {
    "war": 3, "conflict": 3, "attack": 3, "invasion": 3, "sanctions": 3,
    "embargo": 3, "strike": 2, "airstrike": 3, "military": 2, "escalation": 2,
    "disruption": 2, "shortage": 2, "supply cut": 3, "production cut": 2,
    "opec cut": 2, "output cut": 2, "blockade": 3, "tension": 1, "tensions": 1,
    "unrest": 2, "crisis": 3, "threat": 2, "terror": 3, "explosion": 2,
    "pipeline": 2, "refinery": 2, "halt": 2, "suspend": 2, "banning": 2, "ban": 2,
    "drone": 3, "missile": 3, "risk": 1, "concern": 1, "concerns": 1,
    "fear": 2, "fears": 2, "plunge": 2, "surge": 2, "spike": 2, "soar": 2, "soars": 2,
    "rises": 1, "rising": 1, "high": 1, "tariff": 2, "tariffs": 2, "squeeze": 2,
    "red sea": 2, "hormuz": 3, "houthi": 3, "iran": 2, "russia": 2, "tanker": 2
}

POSITIVE_TERMS = {
    "ceasefire": 3, "truce": 3, "peace": 3, "deal": 2, "agreement": 2,
    "surplus": 3, "oversupply": 3, "production increase": 2, "output increase": 2,
    "boost supply": 2, "stable": 2, "stability": 2, "recovery": 2,
    "demand falls": 2, "demand drops": 2, "demand weakens": 2,
    "de-escalation": 3, "resolved": 2, "easing": 2, "eases": 2, "ease": 2,
    "restored": 2, "resume": 2, "resumes": 2, "cooperation": 2, "rebound": 1,
    "stocks fall": 1, "inventory": 1, "cut taxes": 2
}

# Words that, when found right before a matched term, flip its sign
NEGATION_TRIGGERS = ["no ", "not ", "without ", "unlikely ", "eases ", "ease ", "easing "]


def _score_headline(text):
    """Return per-headline pseudo-probabilities in the same shape the old
    FinBERT pipeline returned: [{'label': 'negative', 'score': x}, ...]
    """
    text_lower = text.lower()
    neg_weight = 0.0
    pos_weight = 0.0

    for phrase, weight in NEGATIVE_TERMS.items():
        pattern = r'\b' + re.escape(phrase) + r'\b' if len(phrase) <= 4 else re.escape(phrase)
        for match in re.finditer(pattern, text_lower):
            start = match.start()
            window = text_lower[max(0, start - 12):start]
            if any(trigger in window for trigger in NEGATION_TRIGGERS):
                pos_weight += weight
            else:
                neg_weight += weight

    for phrase, weight in POSITIVE_TERMS.items():
        pattern = r'\b' + re.escape(phrase) + r'\b' if len(phrase) <= 4 else re.escape(phrase)
        for match in re.finditer(pattern, text_lower):
            start = match.start()
            window = text_lower[max(0, start - 12):start]
            if any(trigger in window for trigger in NEGATION_TRIGGERS):
                neg_weight += weight
            else:
                pos_weight += weight

    total = neg_weight + pos_weight
    if total == 0:
        neg, pos, neu = 0.30, 0.30, 0.40
    else:
        neg = max(0.10, min(0.85, 0.30 + (neg_weight / max(1.0, total)) * 0.55))
        pos = max(0.10, min(0.85, 0.30 + (pos_weight / max(1.0, total)) * 0.55))
        neu = max(0.05, 1.0 - neg - pos)

    return [
        {"label": "negative", "score": neg},
        {"label": "positive", "score": pos},
        {"label": "neutral", "score": neu},
    ]


def score_headlines(headlines):
    """Local replacement for the old query_finbert() call. Returns the same
    shape: a list (one per headline) of label/score dicts.
    """
    if not headlines:
        return []
    return [_score_headline(h) for h in headlines]


@app.route("/")
def spotlight():
    return render_template("index.html")


def _fetch_crude_price(crude):
    url = "https://oilprice.com/freewidgets/json_get_oilprices"
    headers = {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
    }
    data = {
        "blend_id": crude["blend_id"],
        "period": 4,
    }
    try:
        response = requests.post(url, headers=headers, data=data, timeout=4)
        return crude, response.json()
    except Exception as e:
        print(f"Error fetching crude {crude['crude_name']}:", e)
        return crude, None


def _fetch_petroleum_price(fuel_type):
    url = "https://apigw.shriramfinance.in/dts-web/lending/api/v2/fuel-prices/price-comparison"
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,en-IN;q=0.8"
    }
    data = {
        "fuel_type": fuel_type,
        "cities": ["Mumbai"]
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=4)
        return fuel_type, response.json()
    except Exception as e:
        print(f"Error fetching petroleum price for {fuel_type}:", e)
        return fuel_type, None


def _fetch_usd_to_inr():
    try:
        response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=4)
        return response.json()
    except Exception as e:
        print("Error fetching USD to INR rate:", e)
        return None


def _fetch_rss_feed(url, source_name):
    try:
        response = requests.get(url, timeout=4)
        feed = feedparser.parse(response.content)
        return source_name, feed
    except Exception as e:
        print(f"Error fetching RSS feed from {source_name}:", e)
        return source_name, None


@app.route("/crude_prices")
def crude_prices():
    all_crude_prices = {}

    crudes = [
        {"blend_id": 46, "crude_name": "BRENT", "default": 75.0},
        {"blend_id": 45, "crude_name": "WTI", "default": 71.0},
        {"blend_id": 29, "crude_name": "OPEC", "default": 74.0},
        {"blend_id": 48, "crude_name": "Oman", "default": 75.0},
        {"blend_id": 144, "crude_name": "Dubai", "default": 74.5},
        {"blend_id": 72, "crude_name": "Indian Basket", "default": 73.5},
    ]

    fuel_types = ["petrol", "diesel"]

    # Execute all network fetches concurrently with ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as executor:
        crude_futures = [executor.submit(_fetch_crude_price, c) for c in crudes]
        fuel_futures = [executor.submit(_fetch_petroleum_price, f) for f in fuel_types]
        usd_future = executor.submit(_fetch_usd_to_inr)
        rss1_future = executor.submit(_fetch_rss_feed, "https://oilprice.com/rss/main", "OilPrice.com")
        rss2_future = executor.submit(_fetch_rss_feed, "https://news.google.com/rss/search?q=oil", "Google News")

        # Process crude prices results
        for future in as_completed(crude_futures):
            crude, result = future.result()
            c_name = crude["crude_name"]
            if result and "last_price" in result:
                all_crude_prices[c_name] = str(result["last_price"]) + " $"
                if c_name == "Indian Basket" and "prices" in result and isinstance(result["prices"], list):
                    all_crude_prices["Indian_Basket_History"] = [
                        {"time": p.get("time"), "price": float(p["price"])}
                        for p in result["prices"][-7:] if "price" in p
                    ]
            else:
                all_crude_prices[c_name] = f"{crude['default']} $"

        # Process petroleum prices results
        for future in as_completed(fuel_futures):
            fuel_type, result = future.result()
            if result and "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                all_crude_prices[fuel_type] = str(result['data'][0]["latest_price"]) + " Rs"
                all_crude_prices[f"{fuel_type}_change"] = str(result['data'][0]["percent_change"]) + " %"
            else:
                default_price = "104.21 Rs" if fuel_type == "petrol" else "92.15 Rs"
                all_crude_prices[fuel_type] = default_price
                all_crude_prices[f"{fuel_type}_change"] = "0.0 %"

        # Process USD to INR rate result
        usd_result = usd_future.result()
        if usd_result and "rates" in usd_result and "INR" in usd_result["rates"]:
            all_crude_prices["USD_to_INR"] = str(round(usd_result['rates']['INR'], 2)) + " Rs"
        else:
            all_crude_prices["USD_to_INR"] = "83.50 Rs"

        # Process RSS feeds results
        feeds1_source, feeds1 = rss1_future.result()
        feeds2_source, feeds2 = rss2_future.result()

    # Get Predicted Indian Basket Price using the pre-loaded model
    def predict_indian_basket_price(brent, wti, opec, dubai, oman):
        new_row = pd.DataFrame([{
            "Brent_Crude_Oil": brent,
            "WTI_Crude_Oil": wti,
            "OPEC_Basket_Price": opec,
            "Dubai_Crude_Price": dubai,
            "Oman_Crude_Price": oman,
        }])
        return model.predict(new_row)[0]

    try:
        result = predict_indian_basket_price(
            brent=float(all_crude_prices["BRENT"].split(" ")[0]),
            wti=float(all_crude_prices["WTI"].split(" ")[0]),
            opec=float(all_crude_prices["OPEC"].split(" ")[0]),
            dubai=float(all_crude_prices["Dubai"].split(" ")[0]),
            oman=float(all_crude_prices["Oman"].split(" ")[0]),
        )
        all_crude_prices["Indian_Basket"] = str(round(result, 2)) + " $"
    except Exception as e:
        print("Error predicting Indian Basket price:", e)
        all_crude_prices["Indian_Basket"] = "74.50 $"

    if "Indian Basket" in all_crude_prices:
        all_crude_prices["Indian_Basket_Actual"] = all_crude_prices["Indian Basket"]
    else:
        all_crude_prices["Indian_Basket_Actual"] = all_crude_prices["Indian_Basket"]

    # Calculate Instability Index based on live news feed using the local scorer
    try:
        news_headlines = []
        live_news = []
        if feeds1 and hasattr(feeds1, "entries"):
            for entry in feeds1.entries[:8]:
                news_headlines.append(entry.title)
                live_news.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": "OilPrice.com",
                    "published": entry.get("published", "Recently")
                })
        if feeds2 and hasattr(feeds2, "entries"):
            for entry in feeds2.entries[:8]:
                news_headlines.append(entry.title)
                live_news.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": "Google News",
                    "published": entry.get("published", "Recently")
                })

        try:
            results = score_headlines(news_headlines)
        except Exception as e:
            print("Error scoring headlines locally:", e)
            results = None

        if results and news_headlines:
            avg_neg, avg_pos, avg_neu = 0.0, 0.0, 0.0
            top_headline = news_headlines[0]
            max_neg_score = -1.0

            for headline, res in zip(news_headlines, results):
                scores = {item['label']: item['score'] for item in res}
                neg = scores.get('negative', 0.0)
                pos = scores.get('positive', 0.0)
                neu = scores.get('neutral', 0.0)
                avg_neg += neg
                avg_pos += pos
                avg_neu += neu

                if neg > max_neg_score:
                    max_neg_score = neg
                    top_headline = headline

            n = len(news_headlines)
            avg_neg /= n
            avg_pos /= n
            avg_neu /= n

            # Calculate dynamic Instability Index (1-100) reflecting net market risk & top peak factor
            net_sentiment_delta = avg_neg - avg_pos
            peak_impact_bonus = (max_neg_score - 0.30) * 35 if max_neg_score > 0.30 else 0
            instability_score = max(15, min(95, int(round(50 + (net_sentiment_delta * 65) + peak_impact_bonus))))

            impact_val = "oil price will rise" if avg_neg >= avg_pos else "oil price will fall"
            reason_val = f"Analysis indicates {'high supply risk and market pressure' if avg_neg >= avg_pos else 'stable market conditions'} (Negative Risk: {avg_neg:.0%}, Positive Stability: {avg_pos:.0%}). Primary headline factor: \"{top_headline}\"."

            all_crude_prices["instability_index"] = instability_score
            all_crude_prices["instability_impact"] = impact_val
            all_crude_prices["instability_reason"] = reason_val
            all_crude_prices["top_headline"] = top_headline

            # Position top headline at index 0 of live_news list
            top_item = None
            other_items = []
            for item in live_news:
                if item["title"] == top_headline and top_item is None:
                    item["is_top"] = True
                    top_item = item
                else:
                    item["is_top"] = False
                    other_items.append(item)

            if top_item:
                live_news = [top_item] + other_items
            elif live_news:
                live_news[0]["is_top"] = True

        else:
            all_crude_prices["instability_index"] = 68
            all_crude_prices["instability_impact"] = "oil price will rise"
            all_crude_prices["instability_reason"] = "Geopolitical tensions in the Middle East and OPEC production cuts are raising supply risk concerns."
            if live_news:
                live_news[0]["is_top"] = True

        all_crude_prices["live_news"] = live_news

    except Exception as e:
        print("Error parsing instability index:", e)
        all_crude_prices["instability_index"] = 68
        all_crude_prices["instability_impact"] = "oil price will rise"
        all_crude_prices["instability_reason"] = "Geopolitical tensions in the Middle East and OPEC production cuts are raising supply risk concerns."
        if "live_news" not in all_crude_prices:
            all_crude_prices["live_news"] = []

    return jsonify(all_crude_prices)


if __name__ == "__main__":
    app.run(debug=True)

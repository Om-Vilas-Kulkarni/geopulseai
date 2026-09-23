from flask import Flask, render_template, jsonify
import requests
import xgboost as xgb
import pandas as pd
import json
import feedparser
import os
from google import genai
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Load the trained XGBoost model once at startup
model = xgb.XGBRegressor()
model.load_model("xgb_model.json")


@app.route("/")
def spotlight():
    return render_template("index.html")

@app.route("/crude_prices")
def crude_prices():
    all_crude_prices = {}

    def get_crude_prices():
        url = "https://oilprice.com/freewidgets/json_get_oilprices"

        headers = {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        }

        crudes = [
            {
                "blend_id": 46,
                "crude_name": "BRENT",
            },
            {
                "blend_id": 45,
                "crude_name": "WTI",
            },
            {
                "blend_id": 29,
                "crude_name": "OPEC",
            },
            {
                "blend_id": 48,
                "crude_name": "Oman",
            },
            {
                "blend_id": 144,
                "crude_name": "Dubai",
            },
            {
                "blend_id": 72,
                "crude_name": "Indian Basket",
            }
        ]

        for crude in crudes:
            data = {
                "blend_id": crude["blend_id"],
                "period": 4,
            }

            response = requests.post(url, headers=headers, data=data)
            result = response.json()
            all_crude_prices[crude["crude_name"]] = str(result["last_price"])+ " $"
            if crude["crude_name"] == "Indian Basket" and "prices" in result and isinstance(result["prices"], list):
                all_crude_prices["Indian_Basket_History"] = [
                    {"time": p.get("time"), "price": float(p["price"])}
                    for p in result["prices"][-7:] if "price" in p
                ]
        
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

        result = predict_indian_basket_price(
            brent=float(all_crude_prices["BRENT"].split(" ")[0]),
            wti=float(all_crude_prices["WTI"].split(" ")[0]),
            opec=float(all_crude_prices["OPEC"].split(" ")[0]),
            dubai=float(all_crude_prices["Dubai"].split(" ")[0]),
            oman=float(all_crude_prices["Oman"].split(" ")[0]),
        )
        all_crude_prices["Indian_Basket"] = str(round(result,2)) + " $"
        if "Indian Basket" in all_crude_prices:
            all_crude_prices["Indian_Basket_Actual"] = all_crude_prices["Indian Basket"]
        else:
            all_crude_prices["Indian_Basket_Actual"] = all_crude_prices["Indian_Basket"]
        
        # Calculate Instability Index based on live news feed using Gemini
        try:
            feeds = feedparser.parse("https://oilprice.com/rss/main")
            feeds2 = feedparser.parse("https://news.google.com/rss/search?q=oil")
            news_headlines = []
            live_news = []
            if feeds and hasattr(feeds, "entries"):
                for entry in feeds.entries[:8]:
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
            
            all_crude_prices["live_news"] = live_news
            req_headlines = ", ".join(news_headlines)
            
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable is not set.")
                
            client = genai.Client(api_key=api_key)
            interaction = client.interactions.create(
                model="gemini-flash-lite-latest",
                input=f"These are the news: {req_headlines}, give me just the json output as 'instability_index' parameter ranging from 1-100, 'impact' parameter which tells oil prices will rise or fall and 'reason' parameter which explains why. Do not format your response in any way (no markdown blocks or prefix/suffix). Just the raw json string.",
            )
            raw_text = interaction.output_text
            cleaned_text = raw_text.replace('```json', "").replace('```', "").strip()
            res_json = json.loads(cleaned_text)
            all_crude_prices["instability_index"] = int(res_json.get("instability_index", 68))
            all_crude_prices["instability_impact"] = res_json.get("impact", "oil price will rise")
            all_crude_prices["instability_reason"] = res_json.get("reason", "Geopolitical tensions in the Middle East and OPEC production cuts are raising supply risk concerns.")
        except Exception as e:
            print("Error parsing instability index:", e)
            all_crude_prices["instability_index"] = 68
            all_crude_prices["instability_impact"] = "oil price will rise"
            all_crude_prices["instability_reason"] = "Geopolitical tensions in the Middle East and OPEC production cuts are raising supply risk concerns."
            if "live_news" not in all_crude_prices:
                all_crude_prices["live_news"] = []
        

    def get_petroleums():
        url = "https://apigw.shriramfinance.in/dts-web/lending/api/v2/fuel-prices/price-comparison"

        headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,en-IN;q=0.8"
        }

        fuel_types = ["petrol","diesel"]
        for fuel_type in fuel_types:
            data = {
                "fuel_type":fuel_type,
                "cities":["Mumbai"]
            }

            response = requests.post(url, headers=headers, json=data)
            result = response.json()
            all_crude_prices[fuel_type] = str(result['data'][0]["latest_price"]) + " Rs"
            all_crude_prices[f"{fuel_type}_change"] = str(result['data'][0]["percent_change"]) + " %"

    def get_USR_to_INR():
        response = requests.get("https://open.er-api.com/v6/latest/USD")
        result = response.json()
        all_crude_prices["USD_to_INR"] = str(round(result['rates']['INR'],2)) + " Rs"

    get_crude_prices()
    get_petroleums()
    get_USR_to_INR()

    return jsonify(all_crude_prices)

if __name__ == "__main__":
    app.run(debug=True)

 
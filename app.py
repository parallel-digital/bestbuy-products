import streamlit as st
import requests
import pandas as pd
import time
import re
import datetime

st.set_page_config(page_title="Best Buy Product Explorer", layout="wide")

# Read API key from Streamlit Secrets (Settings → Secrets)
API_KEY = st.secrets["BESTBUY_API_KEY"]
BASE_URL = "https://api.bestbuy.com/v1"

# ------------------------
# Helpers
# ------------------------
def normalize_sku_input(sku_text: str) -> list[str]:
    """
    Accepts SKUs separated by newlines, tabs, spaces, or commas (works with Excel paste).
    Returns a clean list of SKU strings.
    """
    if not sku_text:
        return []
    skus = re.split(r"[,\s]+", sku_text.strip())
    cleaned = [s.strip().strip('"').strip("'") for s in skus if s.strip().strip('"').strip("'")]
    seen = set()
    out = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def extract_category(product: dict) -> str | None:
    """
    Tries to get a friendly category name from categoryPath list.
    """
    cat_path = product.get("categoryPath") or []
    if isinstance(cat_path, list) and cat_path:
        last = cat_path[-1]
        if isinstance(last, dict):
            name = last.get("name")
            if name:
                return name
    cls = product.get("class")
    if isinstance(cls, dict):
        if cls.get("name"):
            return cls.get("name")
    elif isinstance(cls, str):
        return cls
    return product.get("department")

def safe_get_products(url: str, params: dict, retries: int = 3, backoff: float = 1.5):
    """GET with basic retry/backoff for 403/429."""
    for attempt in range(retries):
        resp = requests.get(url, params=params)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (403, 429):
            time.sleep(backoff * (attempt + 1))
            continue
        st.error(f"Error {resp.status_code}: {resp.text}")
        return None
    st.warning("Rate limit persisted after retries; partial results shown.")
    return None

def fetch_live_prices(sku_list: list[str]) -> dict:
    """
    Fetches real-time pricing using Best Buy's internal pricing API — the same
    source the website uses. This captures active promos that the v1 API's
    salePrice/onSale fields frequently miss due to caching lag.

    Returns a dict keyed by SKU string with keys:
        currentPrice, regularPrice, dollarSavings, percentSavings, onSale, priceEventType
    """
    prices = {}
    if not sku_list:
        return prices

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://www.bestbuy.com/",
    }

    # Best Buy's pricing endpoint — chunk to ~20 SKUs per request
    chunk_size = 20
    for i in range(0, len(sku_list), chunk_size):
        chunk = sku_list[i : i + chunk_size]
        skus_param = "%2C".join(str(s) for s in chunk)  # URL-encoded commas
        url = (
            "https://www.bestbuy.com/api/tcfb/model.json"
            f"?paths=%5B%5B%22shop%22%2C%22magellan%22%2C%22v2%22%2C%22page%22%2C%22tenants%22%2C%22bby%22%2C%22skus%22%2C%5B{skus_param}%5D%2C%22prices%22%5D%5D"
            "&method=get"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue
            data = resp.json()
            skus_data = (
                data.get("jsonGraph", {})
                    .get("shop", {})
                    .get("magellan", {})
                    .get("v2", {})
                    .get("page", {})
                    .get("tenants", {})
                    .get("bby", {})
                    .get("skus", {})
            )
            for sku in chunk:
                sku_str = str(sku)
                pricing = skus_data.get(sku_str, {}).get("prices", {}).get("value", {})
                if not pricing:
                    continue
                current = pricing.get("currentPrice") or pricing.get("customerPrice")
                regular = pricing.get("regularPrice")
                if current is None:
                    continue
                dollar_savings = round(regular - current, 2) if (regular and current < regular) else 0.0
                pct_savings = round(dollar_savings / regular * 100, 1) if (regular and dollar_savings > 0) else 0.0
                event_type = pricing.get("priceEventType", "regular")
                prices[sku_str] = {
                    "currentPrice": current,
                    "regularPrice_live": regular,
                    "dollarSavings": dollar_savings,
                    "percentSavings": pct_savings,
                    "onSale": dollar_savings > 0,
                    "priceEventType": event_type,
                }
        except Exception:
            pass
        time.sleep(0.2)

    return prices

def build_rows(products: list, live_prices: dict) -> list:
    """
    Merge v1 API product fields with live pricing data.
    currentPrice from the live endpoint is used as the authoritative price.
    """
    rows = []
    for product in products:
        sku = str(product.get("sku", ""))
        live = live_prices.get(sku, {})

        # Prefer live current price; fall back to v1 salePrice
        current_price = live.get("currentPrice", product.get("salePrice"))
        regular_price = live.get("regularPrice_live") or product.get("regularPrice")
        dollar_savings = live.get("dollarSavings", product.get("dollarSavings"))
        pct_savings = live.get("percentSavings", product.get("percentSavings"))
        on_sale = live.get("onSale", product.get("onSale"))
        price_event = live.get("priceEventType", "")

        rows.append({
            "sku": sku,
            "name": product.get("name"),
            "brand": product.get("manufacturer"),
            "modelNumber": product.get("modelNumber"),
            "category": extract_category(product),
            "regularPrice": regular_price,
            "currentPrice": current_price,
            "dollarSavings": dollar_savings if dollar_savings else None,
            "percentSavings": pct_savings if pct_savings else None,
            "onSale": on_sale,
            "priceEventType": price_event if price_event and price_event != "regular" else None,
            "onlineAvailability": product.get("onlineAvailability"),
            "url": product.get("url"),
        })
    return rows

def fetch_products_by_skus(sku_list: list[str]) -> pd.DataFrame:
    """
    Fetch up to 100 SKUs per request via v1 API, then enrich with live pricing.
    """
    if not sku_list:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_products = []
    chunk_size = 100
    progress = st.progress(0)
    total_chunks = (len(sku_list) + chunk_size - 1) // chunk_size

    for idx in range(0, len(sku_list), chunk_size):
        chunk = sku_list[idx : idx + chunk_size]
        skus_joined = ",".join(chunk)
        url = f"{BASE_URL}/products(sku in({skus_joined}))"
        params = {
            "apiKey": API_KEY,
            "format": "json",
            "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onSale,dollarSavings,percentSavings,onlineAvailability,categoryPath,url",
            "pageSize": 100,
        }
        data = safe_get_products(url, params)
        if data and isinstance(data, dict):
            all_products.extend(data.get("products", []))
        progress.progress(min((idx // chunk_size + 1) / total_chunks, 1.0))
        time.sleep(0.3)

    if not all_products:
        return pd.DataFrame()

    # Fetch live prices for all retrieved SKUs
    fetched_skus = [str(p.get("sku", "")) for p in all_products]
    live_prices = fetch_live_prices(fetched_skus)

    rows = build_rows(all_products, live_prices)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["data_pull_time"] = run_ts
    return df

def fetch_products_by_keyword(keyword: str) -> pd.DataFrame:
    if not keyword:
        return pd.DataFrame()
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    url = f"{BASE_URL}/products((search={keyword}))"
    params = {
        "apiKey": API_KEY,
        "format": "json",
        "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onSale,dollarSavings,percentSavings,onlineAvailability,categoryPath,url",
        "pageSize": 100,
        "page": 1,
    }

    all_products = []
    while True:
        data = safe_get_products(url, params)
        if not data:
            break
        products = data.get("products", [])
        all_products.extend(products)
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    if not all_products:
        return pd.DataFrame()

    fetched_skus = [str(p.get("sku", "")) for p in all_products]
    live_prices = fetch_live_prices(fetched_skus)
    rows = build_rows(all_products, live_prices)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["data_pull_time"] = run_ts
    return df

def fetch_products_by_category(category_id: str) -> pd.DataFrame:
    if not category_id:
        return pd.DataFrame()
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    url = f"{BASE_URL}/products(categoryPath.id={category_id})"
    params = {
        "apiKey": API_KEY,
        "format": "json",
        "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onSale,dollarSavings,percentSavings,onlineAvailability,categoryPath,url",
        "pageSize": 100,
        "page": 1,
    }

    all_products = []
    while True:
        data = safe_get_products(url, params)
        if not data:
            break
        products = data.get("products", [])
        all_products.extend(products)
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    if not all_products:
        return pd.DataFrame()

    fetched_skus = [str(p.get("sku", "")) for p in all_products]
    live_prices = fetch_live_prices(fetched_skus)
    rows = build_rows(all_products, live_prices)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["data_pull_time"] = run_ts
    return df

# ------------------------
# UI
# ------------------------
st.title("Best Buy Product Explorer")

mode = st.sidebar.radio("Choose an input method:", ("SKU List", "Keyword Search", "Category Browse"))

if mode == "SKU List":
    st.subheader("Search by SKU list")
    sku_input = st.text_area(
        "Paste SKUs (commas, spaces, tabs, or one-per-line are all OK):",
        height=180,
        placeholder="6401728\n6535962\n6510256"
    )
    if st.button("Fetch by SKUs"):
        skus = normalize_sku_input(sku_input)
        if not skus:
            st.warning("Please paste at least one SKU.")
        else:
            df = fetch_products_by_skus(skus)
            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Found {len(df)} products.")
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "Download CSV",
                    df.to_csv(index=False),
                    "products.csv",
                    "text/csv"
                )

elif mode == "Keyword Search":
    st.subheader("Search by keyword")
    keyword = st.text_input("Keyword")
    if st.button("Search"):
        if not keyword:
            st.warning("Please enter a keyword.")
        else:
            df = fetch_products_by_keyword(keyword)
            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Found {len(df)} products.")
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "Download CSV",
                    df.to_csv(index=False),
                    "products.csv",
                    "text/csv"
                )

elif mode == "Category Browse":
    st.subheader("Browse by Category ID")
    category_id = st.text_input("Category ID (e.g., abcat0502000)")
    if st.button("Browse Category"):
        if not category_id:
            st.warning("Please enter a category ID.")
        else:
            df = fetch_products_by_category(category_id)
            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Found {len(df)} products.")
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "Download CSV",
                    df.to_csv(index=False),
                    "products.csv",
                    "text/csv"
                )


# Custom CSS
st.markdown(
    """
    <style>
    div.stButton > button {
        background-color: #0f8b8d;
        color: white;
        border-radius: 8px;
        padding: 0.5em 1em;
        font-size: 16px;
    }
    div.stButton > button:hover {
        background-color: #f49f0a;
        color: white;
    }
    div.stDownloadButton > button {
        background-color: #0f8b8d;
        color: white;
        border-radius: 8px;
        padding: 0.5em 1em;
        font-size: 16px;
    }
    div.stDownloadButton > button:hover {
        background-color: #f49f0a;
        color: white;
    }
    div[data-testid="stDataFrame"] div.row_heading,
    div[data-testid="stDataFrame"] div.column_heading,
    div[data-testid="stDataFrame"] div.dataframe td {
        background-color: #ffffff !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

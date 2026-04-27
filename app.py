import streamlit as st
import requests
import pandas as pd
import time
import re
import datetime
from urllib.parse import quote
from typing import Optional

st.set_page_config(page_title="Best Buy Product Explorer", layout="wide")

# Read API key from Streamlit Secrets (Settings -> Secrets)
API_KEY = st.secrets["BESTBUY_API_KEY"]
BASE_URL = "https://api.bestbuy.com/v1"
MAX_PAGE_SIZE = 100

SHOW_FIELDS = ",".join([
    "sku", "name", "manufacturer", "modelNumber",
    "salePrice", "regularPrice", "onSale",
    "url", "image", "categoryPath",
    "customerReviewAverage", "customerReviewCount"
])

# ------------------------
# Helpers
# ------------------------

def normalize_sku_input(sku_text: str):
    """
    Accepts SKUs separated by newlines, tabs, spaces, or commas.
    Returns (valid_skus list, invalid_tokens list).
    """
    if not sku_text:
        return [], []

    tokens = re.split(r"[,\s]+", sku_text.strip())

    cleaned = []
    invalid = []

    for t in tokens:
        if not t:
            continue
        t = t.strip().strip('"').strip("'")
        digits = re.sub(r"\D", "", t)
        if digits:
            cleaned.append(digits)
        elif t:
            invalid.append(t)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)

    return out, invalid


def extract_category(product: dict) -> Optional[str]:
    """
    Tries to get a friendly category name.
    Prefers the last element of categoryPath; falls back to class or department.
    """
    cat_path = product.get("categoryPath") or []
    if isinstance(cat_path, list) and cat_path:
        last = cat_path[-1]
        if isinstance(last, dict):
            name = last.get("name")
            if name:
                return name
    return product.get("class") or product.get("department")


def safe_get(url: str, params: dict, retries: int = 3, backoff: float = 1.5, timeout: int = 20):
    """
    GET with retry/backoff for 403/429. Returns parsed JSON dict or None.
    Always uses params= dict so requests handles encoding; never manually concatenates apiKey.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
        except Exception as e:
            st.error(f"Request exception: {e}")
            return None

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in (403, 429):
            time.sleep(backoff * (attempt + 1))
            continue

        st.error(f"API error {resp.status_code}: {resp.text[:600]}")
        return None

    st.warning("Rate limit persisted after retries; partial results may be shown.")
    return None


def products_to_df(products: list, run_ts: str) -> pd.DataFrame:
    """
    Convert a list of Best Buy product dicts into a DataFrame with consistent pricing columns.
    """
    rows = []
    for p in products or []:
        sale = p.get("salePrice")
        regular = p.get("regularPrice")
        on_sale = p.get("onSale")

        savings = None
        pct_off = None
        if sale is not None and regular is not None and regular > 0 and sale <= regular:
            savings = round(regular - sale, 2)
            pct_off = round((regular - sale) / regular, 4)

        rows.append({
            "run_timestamp": run_ts,
            "sku": p.get("sku"),
            "name": p.get("name"),
            "category": extract_category(p),
            "manufacturer": p.get("manufacturer"),
            "modelNumber": p.get("modelNumber"),
            "url": p.get("url"),
            "image": p.get("image"),
            "salePrice": sale,
            "regularPrice": regular,
            "onSale": on_sale,
            "savings": savings,
            "pctOff": pct_off,
            "customerReviewAverage": p.get("customerReviewAverage"),
            "customerReviewCount": p.get("customerReviewCount"),
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner=False)
def fetch_batch(skus_tuple: tuple) -> list:
    """
    Cached fetch for a single batch of SKUs (tuple used as cache key).
    URL-encodes the space in 'sku in(...)' so the API can parse it correctly.
    """
    sku_filter = f"(sku in({','.join(skus_tuple)}))"
    # URL-encode the space in 'sku in' -> 'sku%20in'; keep (),= unencoded
    encoded_filter = quote(sku_filter, safe="(),=")
    url = f"{BASE_URL}/products{encoded_filter}.json"

    params = {
        "apiKey": API_KEY,
        "show": SHOW_FIELDS,
        "pageSize": MAX_PAGE_SIZE,
    }

    data = safe_get(url, params=params)
    if not data:
        return []
    return data.get("products", [])


def fetch_products_by_skus(sku_list: list) -> pd.DataFrame:
    """
    Fetch SKUs in batches of 100 using the sku in(...) filter.
    Returns a DataFrame including rows for SKUs not found by the API.
    """
    if not sku_list:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_products = []

    total_chunks = (len(sku_list) + MAX_PAGE_SIZE - 1) // MAX_PAGE_SIZE
    progress = st.progress(0)

    for i, start in enumerate(range(0, len(sku_list), MAX_PAGE_SIZE)):
        batch = tuple(sku_list[start:start + MAX_PAGE_SIZE])
        all_products.extend(fetch_batch(batch))
        progress.progress(min((i + 1) / total_chunks, 1.0))
        time.sleep(0.3)

    df = products_to_df(all_products, run_ts)

    # Add placeholder rows for SKUs not returned by API
    if not df.empty:
        found = set(df["sku"].astype(str).tolist())
    else:
        found = set()

    missing = [s for s in sku_list if s not in found]
    if missing:
        missing_rows = pd.DataFrame([{
            "run_timestamp": run_ts,
            "sku": s,
            "name": None, "category": None, "manufacturer": None,
            "modelNumber": None, "url": None, "image": None,
            "salePrice": None, "regularPrice": None, "onSale": None,
            "savings": None, "pctOff": None,
            "customerReviewAverage": None, "customerReviewCount": None,
            "note": "SKU not returned by API"
        } for s in missing])
        df = pd.concat([df, missing_rows], ignore_index=True)

    return df


def fetch_products_by_keyword(keyword: str) -> pd.DataFrame:
    """
    Search Best Buy products by keyword (up to 100 results).
    """
    if not keyword:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    encoded_kw = quote(keyword, safe="")
    url = f"{BASE_URL}/products(search={encoded_kw}).json"

    params = {
        "apiKey": API_KEY,
        "show": SHOW_FIELDS,
        "pageSize": 100,
        "page": 1,
    }

    all_products = []
    while True:
        data = safe_get(url, params=params)
        if not data:
            break
        products = data.get("products", [])
        all_products.extend(products)
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    return products_to_df(all_products, run_ts)


def fetch_products_by_category(category_id: str) -> pd.DataFrame:
    """
    Browse Best Buy products by category ID (up to 100 results per page).
    """
    if not category_id:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE_URL}/products(categoryPath.id={category_id}).json"

    params = {
        "apiKey": API_KEY,
        "show": SHOW_FIELDS,
        "pageSize": 100,
        "page": 1,
    }

    all_products = []
    while True:
        data = safe_get(url, params=params)
        if not data:
            break
        products = data.get("products", [])
        all_products.extend(products)
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    return products_to_df(all_products, run_ts)


# ------------------------
# UI
# ------------------------

st.title("Best Buy Product Explorer")

mode = st.sidebar.radio("Choose an input method:", ("SKU List", "Keyword Search", "Category Browse"))
debug = st.sidebar.checkbox("Debug mode (show raw price fields)", value=False)

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.sidebar.success("Cache cleared.")

# ---- SKU List ----
if mode == "SKU List":
    st.subheader("Search by SKU list")
    sku_input = st.text_area(
        "Paste SKUs (commas, spaces, tabs, or one-per-line are all OK):",
        height=180,
        placeholder="6401728\n6535962\n6510256"
    )

    if st.button("Fetch by SKUs"):
        skus, invalid = normalize_sku_input(sku_input)

        if invalid:
            st.info(f"Ignored {len(invalid)} invalid token(s): {invalid[:10]}{'...' if len(invalid) > 10 else ''}")

        if not skus:
            st.warning("Please paste at least one valid numeric SKU.")
        else:
            st.caption(f"Fetching {len(skus)} unique SKU(s)...")
            df = fetch_products_by_skus(skus)

            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Returned {len(df)} row(s).")

                if debug:
                    debug_cols = ["sku", "salePrice", "regularPrice", "onSale", "savings", "pctOff"]
                    if "note" in df.columns:
                        debug_cols.append("note")
                    st.dataframe(df[debug_cols], use_container_width=True)
                else:
                    st.dataframe(df, use_container_width=True)

                st.download_button(
                    "Download CSV",
                    df.to_csv(index=False),
                    "products.csv",
                    "text/csv"
                )

# ---- Keyword Search ----
elif mode == "Keyword Search":
    st.subheader("Search by keyword")
    keyword = st.text_input("Keyword")

    if st.button("Search"):
        if not keyword:
            st.warning("Please enter a keyword.")
        else:
            with st.spinner("Searching..."):
                df = fetch_products_by_keyword(keyword)
            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Found {len(df)} product(s).")
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "Download CSV",
                    df.to_csv(index=False),
                    "products.csv",
                    "text/csv"
                )

# ---- Category Browse ----
elif mode == "Category Browse":
    st.subheader("Browse by Category ID")
    category_id = st.text_input("Category ID (e.g., abcat0502000)")

    if st.button("Browse Category"):
        if not category_id:
            st.warning("Please enter a category ID.")
        else:
            with st.spinner("Browsing..."):
                df = fetch_products_by_category(category_id)
            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Found {len(df)} product(s).")
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
    </style>
    """,
    unsafe_allow_html=True
)

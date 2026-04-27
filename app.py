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
MAX_PAGE_SIZE = 100  # Best practice for performance

# ------------------------
# Helpers
# ------------------------

def normalize_sku_input(sku_text: str) -> tuple[list[str], list[str]]:
    """
    Accepts SKUs separated by newlines, tabs, spaces, or commas (works with Excel paste).
    Returns (valid_skus, invalid_tokens).
    """
    if not sku_text:
        return [], []

    # Split on commas OR ANY whitespace
    tokens = re.split(r"[,\s]+", sku_text.strip())

    cleaned = []
    invalid = []

    for t in tokens:
        if not t:
            continue
        t = t.strip().strip('"').strip("'")

        # keep only digits (Best Buy SKUs are numeric)
        digits = re.sub(r"\D", "", t)
        if digits:
            cleaned.append(digits)
        else:
            invalid.append(t)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)

    return out, invalid


def extract_category(product: dict) -> str | None:
    """
    Tries to get a friendly category name.
    Prefers the last element of categoryPath.name; falls back to 'class' or 'department'.
    """
    cat_path = product.get("categoryPath") or []
    if isinstance(cat_path, list) and cat_path:
        last = cat_path[-1]
        if isinstance(last, dict):
            name = last.get("name")
            if name:
                return name

    # Common fallbacks if present
    return product.get("class") or product.get("department")


def safe_get(url: str, params: dict, retries: int = 3, backoff: float = 1.5, timeout: int = 20):
    """
    GET with retry/backoff for 403/429. Returns JSON dict or None.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PDS-BestBuy-Explorer/1.0)"
    }

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except Exception as e:
            st.error(f"Request failed: {e}")
            return None

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in (403, 429):
            time.sleep(backoff * (attempt + 1))
            continue

        st.error(f"API error {resp.status_code}: {resp.text[:500]}")
        return None

    st.warning("Rate limit persisted after retries; partial results may be shown.")
    return None


def products_to_df(products: list[dict], run_ts: str) -> pd.DataFrame:
    """
    Convert Best Buy product dicts into a dataframe with consistent pricing columns.
    """
    rows = []
    for p in products or []:
        sale = p.get("salePrice")
        regular = p.get("regularPrice")
        on_sale = p.get("onSale")

        # Promo calculations (guarding None)
        savings = None
        pct_off = None
        if sale is not None and regular is not None and regular and sale <= regular:
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
def fetch_products_batch_by_skus(skus: tuple[str, ...]) -> list[dict]:
    """
    Cached fetch for a single SKU batch (tuple for cache key stability).
    """
    sku_filter = f"(sku in({','.join(skus)}))"
    url = f"{BASE_URL}/products{sku_filter}.json"

    params = {
        "apiKey": API_KEY,
        "show": ",".join([
            "sku", "name", "manufacturer", "modelNumber",
            "salePrice", "regularPrice", "onSale",
            "url", "image",
            "categoryPath",
            "customerReviewAverage", "customerReviewCount"
        ])
    }

    data = safe_get(url, params=params)
    if not data:
        return []

    return data.get("products", [])


def fetch_products_by_skus(sku_list: list[str]) -> pd.DataFrame:
    """
    Fetch SKUs in batches of 100 using 'sku in(...)'.
    """
    if not sku_list:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_products = []

    for i in range(0, len(sku_list), MAX_PAGE_SIZE):
        batch = tuple(sku_list[i:i + MAX_PAGE_SIZE])
        all_products.extend(fetch_products_batch_by_skus(batch))

    df = products_to_df(all_products, run_ts)

    # Ensure we return rows for SKUs that were requested but not found
    if not df.empty:
        found = set(df["sku"].astype(str).tolist())
    else:
        found = set()

    missing = [s for s in sku_list if s not in found]
    if missing:
        missing_rows = pd.DataFrame([{
            "run_timestamp": run_ts,
            "sku": s,
            "name": None,
            "category": None,
            "manufacturer": None,
            "modelNumber": None,
            "url": None,
            "image": None,
            "salePrice": None,
            "regularPrice": None,
            "onSale": None,
            "savings": None,
            "pctOff": None,
            "customerReviewAverage": None,
            "customerReviewCount": None,
            "note": "SKU not returned by API"
        } for s in missing])
        df = pd.concat([df, missing_rows], ignore_index=True)

    return df


def fetch_products_by_keyword(keyword: str) -> pd.DataFrame:
    if not keyword:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE_URL}/products(search={keyword}).json"

    params = {
        "apiKey": API_KEY,
        "pageSize": 50,
        "show": ",".join([
            "sku", "name", "manufacturer", "modelNumber",
            "salePrice", "regularPrice", "onSale",
            "url", "image",
            "categoryPath",
            "customerReviewAverage", "customerReviewCount"
        ])
    }

    data = safe_get(url, params=params)
    products = (data or {}).get("products", [])
    return products_to_df(products, run_ts)


def fetch_products_by_category(category_id: str) -> pd.DataFrame:
    if not category_id:
        return pd.DataFrame()

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE_URL}/products(categoryPath.id={category_id}).json"

    params = {
        "apiKey": API_KEY,
        "pageSize": 50,
        "show": ",".join([
            "sku", "name", "manufacturer", "modelNumber",
            "salePrice", "regularPrice", "onSale",
            "url", "image",
            "categoryPath",
            "customerReviewAverage", "customerReviewCount"
        ])
    }

    data = safe_get(url, params=params)
    products = (data or {}).get("products", [])
    return products_to_df(products, run_ts)


# ------------------------
# UI
# ------------------------

st.title("Best Buy Product Explorer")

mode = st.sidebar.radio("Choose an input method:", ("SKU List", "Keyword Search", "Category Browse"))
debug = st.sidebar.checkbox("Debug mode (show raw price fields)", value=False)

if mode == "SKU List":
    st.subheader("Search by SKU list")
    sku_input = st.text_area(
        "Paste SKUs (commas, spaces, tabs, or one-per-line are all OK):",
        height=180,
        placeholder="6401728\n6535962\n6510256"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        fetch_btn = st.button("Fetch by SKUs")
    with col2:
        if st.button("Clear cache"):
            st.cache_data.clear()
            st.success("Cache cleared.")

    if fetch_btn:
        skus, invalid = normalize_sku_input(sku_input)

        if invalid:
            st.info(f"Ignored {len(invalid)} invalid tokens: {invalid[:10]}{'...' if len(invalid) > 10 else ''}")

        if not skus:
            st.warning("Please paste at least one valid numeric SKU.")
        else:
            st.caption(f"Parsed {len(skus)} unique SKUs.")
            df = fetch_products_by_skus(skus)

            if df.empty:
                st.warning("No products found.")
            else:
                st.success(f"Returned {len(df)} rows.")

                if debug:
                    st.dataframe(df[["sku", "salePrice", "regularPrice", "onSale", "savings", "pctOff", "note"]] if "note" in df.columns
                                 else df[["sku", "salePrice", "regularPrice", "onSale", "savings", "pctOff"]],
                                 use_container_width=True)
                else:
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
    </style>
    """,
    unsafe_allow_html=True
)
``
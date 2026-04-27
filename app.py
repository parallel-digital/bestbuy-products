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
    # Split on commas OR ANY whitespace
    skus = re.split(r"[,\s]+", sku_text.strip())
    # Strip quotes and keep non-empty
    cleaned = [s.strip().strip('"').strip("'") for s in skus if s.strip().strip('"').strip("'")]
    # Deduplicate while preserving order
    seen = set()
    out = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def extract_category(product: dict) -> str | None:
    """
    Tries to get a friendly category name.
    Prefers the last element of categoryPath.name; falls back to 'class' or 'department'.
    """
    # categoryPath is usually a list of dicts: [{'name': 'Category'}, ...]
    cat_path = product.get("categoryPath") or []
    if isinstance(cat_path, list) and cat_path:
        last = cat_path[-1]
        if isinstance(last, dict):
            name = last.get("name")
            if name:
                return name

    # Sometimes 'class' is present as a string or a dict with 'name'
    cls = product.get("class")
    if isinstance(cls, dict):
        if cls.get("name"):
            return cls.get("name")
    elif isinstance(cls, str):
        return cls

    # Fallback
    return product.get("department")

def safe_get_products(url: str, params: dict, retries: int = 3, backoff: float = 1.5):
    """
    GET with basic retry/backoff for 403/429.
    """
    for attempt in range(retries):
        resp = requests.get(url, params=params)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (403, 429):
            time.sleep(backoff * (attempt + 1))
            continue
        # For other errors, surface and stop
        st.error(f"Error {resp.status_code}: {resp.text}")
        return None
    st.warning("Rate limit persisted after retries; partial results shown.")
    return None

def fetch_products_by_skus(sku_list: list[str]) -> pd.DataFrame:
    """
    Fetch up to 100 SKUs per request using 'sku in(...)' for performance.
    Adds a run-level timestamp column; returns a DataFrame.
    """
    if not sku_list:
        return pd.DataFrame()

    # Same timestamp for all rows in this run
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_rows = []
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
            # Only ask for attributes allowed by Best Buy API
            "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onlineAvailability,categoryPath.name,url",
            "pageSize": 100,
        }

        data = safe_get_products(url, params)
        if data and isinstance(data, dict):
            for product in data.get("products", []):
                all_rows.append({
                    "sku": product.get("sku"),
                    "name": product.get("name"),
                    "brand": product.get("manufacturer"),
                    "modelNumber": product.get("modelNumber"),
                    "category": extract_category(product),
                    "regularPrice": product.get("regularPrice"),
                    "salePrice": product.get("salePrice"),
                    "onlineAvailability": product.get("onlineAvailability"),
                    "url": product.get("url"),
                })

        progress.progress(min((idx // chunk_size + 1) / total_chunks, 1.0))
        time.sleep(0.3)  # stay under per-second limits

    df = pd.DataFrame(all_rows)
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
        "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onlineAvailability,categoryPath.name,url",
        "pageSize": 100,
        "page": 1,
    }

    all_rows = []
    while True:
        data = safe_get_products(url, params)
        if not data:
            break
        products = data.get("products", [])
        for product in products:
            all_rows.append({
                "sku": product.get("sku"),
                "name": product.get("name"),
                "brand": product.get("manufacturer"),
                "modelNumber": product.get("modelNumber"),
                "category": extract_category(product),
                "regularPrice": product.get("regularPrice"),
                "salePrice": product.get("salePrice"),
                "onlineAvailability": product.get("onlineAvailability"),
                "url": product.get("url"),
            })
        # Stop if fewer than pageSize returned (no more pages)
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    df = pd.DataFrame(all_rows)
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
        "show": "sku,name,modelNumber,manufacturer,regularPrice,salePrice,onlineAvailability,categoryPath.name,url",
        "pageSize": 100,
        "page": 1,
    }

    all_rows = []
    while True:
        data = safe_get_products(url, params)
        if not data:
            break
        products = data.get("products", [])
        for product in products:
            all_rows.append({
                "sku": product.get("sku"),
                "name": product.get("name"),
                "brand": product.get("manufacturer"),
                "modelNumber": product.get("modelNumber"),
                "category": extract_category(product),
                "regularPrice": product.get("regularPrice"),
                "salePrice": product.get("salePrice"),
                "onlineAvailability": product.get("onlineAvailability"),
                "url": product.get("url"),
            })
        if len(products) < params["pageSize"]:
            break
        params["page"] += 1
        time.sleep(0.3)

    df = pd.DataFrame(all_rows)
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
    /* Normal button style */
    div.stButton > button {
        background-color: #0f8b8d;  /* main button color */
        color: white;               /* text color */
        border-radius: 8px;         /* rounded corners */
        padding: 0.5em 1em;         /* padding */
        font-size: 16px;            /* font size */
    }
    div.stButton > button:hover {
        background-color: #f49f0a;  /* hover color */
        color: white;               /* text color on hover */
    }

    div.stDownloadButton > button {
        background-color: #0f8b8d;  /* button color */
        color: white;               /* text color */
        border-radius: 8px;         /* rounded corners */
        padding: 0.5em 1em;
        font-size: 16px;
    }
    div.stDownloadButton > button:hover {
        background-color: #f49f0a;  /* hover color */
        color: white;
    }
    /* Background color of the table cells */
    div[data-testid="stDataFrame"] div.row_heading,
    div[data-testid="stDataFrame"] div.column_heading,
    div[data-testid="stDataFrame"] div.dataframe td {
        background-color: #ffffff !important;  /* your table background color */
    }
    </style>
    """,
    unsafe_allow_html=True
)

    

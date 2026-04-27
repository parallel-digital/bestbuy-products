import streamlit as st
import requests
import pandas as pd
import time
import re
import datetime

st.set_page_config(page_title="Best Buy Product Explorer", layout="wide")

API_KEY = st.secrets["BESTBUY_API_KEY"]
BASE_URL = "https://api.bestbuy.com/v1"

SHOW_FIELDS = (
    "sku,name,modelNumber,manufacturer,regularPrice,salePrice,"
    "onSale,dollarSavings,percentSavings,onlineAvailability,"
    "categoryPath,url,image"
)

# ------------------------
# Helpers
# ------------------------
def normalize_sku_input(sku_text: str) -> list[str]:
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
    cat_path = product.get("categoryPath") or []
    if isinstance(cat_path, list) and cat_path:
        last = cat_path[-1]
        if isinstance(last, dict):
            name = last.get("name")
            if name:
                return name
    cls = product.get("class")
    if isinstance(cls, dict):
        return cls.get("name")
    elif isinstance(cls, str):
        return cls
    return product.get("department")

def safe_get_products(url: str, params: dict, retries: int = 3, backoff: float = 1.5):
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

def build_rows(products: list) -> list:
    rows = []
    for product in products:
        sku = str(product.get("sku", ""))
        regular = product.get("regularPrice")
        sale = product.get("salePrice")

        if regular is not None and sale is not None and sale < regular:
            dollar_savings = round(regular - sale, 2)
            pct_savings = round(dollar_savings / regular * 100, 1)
            on_sale = True
            current_price = sale
            verify_price = False
        else:
            dollar_savings = None
            pct_savings = None
            on_sale = False
            current_price = sale if sale is not None else regular
            verify_price = (regular is not None and sale is not None and sale == regular)

        rows.append({
            "sku": sku,
            "image": product.get("image", ""),
            "name": product.get("name"),
            "brand": product.get("manufacturer"),
            "modelNumber": product.get("modelNumber"),
            "category": extract_category(product),
            "regularPrice": regular,
            "currentPrice": current_price,
            "dollarSavings": dollar_savings,
            "percentSavings": pct_savings,
            "onSale": on_sale,
            "verify_price": verify_price,
            "onlineAvailability": product.get("onlineAvailability"),
            "url": product.get("url", ""),
        })
    return rows

# ------------------------
# Fetch functions
# ------------------------
def fetch_products_by_skus(sku_list: list[str]) -> pd.DataFrame:
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
        params = {"apiKey": API_KEY, "format": "json", "show": SHOW_FIELDS, "pageSize": 100}
        data = safe_get_products(url, params)
        if data and isinstance(data, dict):
            all_products.extend(data.get("products", []))
        progress.progress(min((idx // chunk_size + 1) / total_chunks, 1.0))
        time.sleep(0.3)

    if not all_products:
        return pd.DataFrame()

    df = pd.DataFrame(build_rows(all_products))
    df["data_pull_time"] = run_ts
    return df

def fetch_products_by_keyword(keyword: str) -> pd.DataFrame:
    if not keyword:
        return pd.DataFrame()
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE_URL}/products((search={keyword}))"
    params = {"apiKey": API_KEY, "format": "json", "show": SHOW_FIELDS, "pageSize": 100, "page": 1}

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
    df = pd.DataFrame(build_rows(all_products))
    df["data_pull_time"] = run_ts
    return df

def fetch_products_by_category(category_id: str) -> pd.DataFrame:
    if not category_id:
        return pd.DataFrame()
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE_URL}/products(categoryPath.id={category_id})"
    params = {"apiKey": API_KEY, "format": "json", "show": SHOW_FIELDS, "pageSize": 100, "page": 1}

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
    df = pd.DataFrame(build_rows(all_products))
    df["data_pull_time"] = run_ts
    return df

# ------------------------
# Rendering
# ------------------------
def fmt_price(val):
    if val is None:
        return ""
    return f"${val:,.2f}"

def fmt_pct(val):
    if val is None:
        return ""
    return f"{val:.1f}%"

def render_html_table(df: pd.DataFrame) -> str:
    rows_html = ""
    for _, row in df.iterrows():
        img_url = row.get("image", "")
        product_url = row.get("url", "")
        name = row.get("name", "")
        on_sale = row.get("onSale", False)
        verify = row.get("verify_price", False)
        dollar_sav = row.get("dollarSavings")
        pct_sav = row.get("percentSavings")
        current = row.get("currentPrice")
        regular = row.get("regularPrice")

        # Image cell — loads client-side in the user's browser
        if img_url:
            img_cell = f'<img src="{img_url}" style="width:70px;height:70px;object-fit:contain;border-radius:4px;">'
        else:
            img_cell = '<span style="color:#aaa;font-size:11px;">No image</span>'

        # Name cell with clickable link
        if product_url:
            name_cell = f'<a href="{product_url}" target="_blank" style="color:#0f8b8d;font-weight:600;text-decoration:none;">{name}</a>'
        else:
            name_cell = name

        # Price cell
        if on_sale:
            price_cell = (
                f'<span style="color:#cc0000;font-weight:700;">{fmt_price(current)}</span>'
                f'<br><span style="text-decoration:line-through;color:#888;font-size:11px;">{fmt_price(regular)}</span>'
                f'<br><span style="color:#2a7a2a;font-size:11px;">Save {fmt_price(dollar_sav)} ({fmt_pct(pct_sav)})</span>'
            )
        elif verify:
            price_cell = (
                f'<span style="font-weight:600;">{fmt_price(current)}</span>'
                f'<br><span style="color:#e07b00;font-size:11px;">⚠️ Check site for promos</span>'
            )
        else:
            price_cell = f'<span style="font-weight:600;">{fmt_price(current)}</span>'

        avail = row.get("onlineAvailability")
        avail_cell = (
            '<span style="color:#2a7a2a;">✔ In Stock</span>'
            if avail else
            '<span style="color:#cc0000;">✘ Unavailable</span>'
        )

        rows_html += f"""
        <tr>
            <td style="text-align:center;vertical-align:middle;padding:8px 6px;">{img_cell}</td>
            <td style="vertical-align:middle;padding:8px 6px;">{name_cell}
                <br><span style="color:#888;font-size:11px;">{row.get('brand','')} &nbsp;|&nbsp; SKU: {row.get('sku','')}</span>
                <br><span style="color:#aaa;font-size:11px;">{row.get('category','')}</span>
            </td>
            <td style="vertical-align:middle;padding:8px 6px;white-space:nowrap;">{price_cell}</td>
            <td style="vertical-align:middle;padding:8px 6px;font-size:12px;">{avail_cell}</td>
            <td style="vertical-align:middle;padding:8px 6px;font-size:12px;color:#555;">{row.get('data_pull_time','')}</td>
        </tr>"""

    table_html = f"""
    <style>
        .bby-table {{
            width: 100%;
            border-collapse: collapse;
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 13px;
        }}
        .bby-table th {{
            background-color: #0f8b8d;
            color: white;
            padding: 10px 8px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}
        .bby-table td {{
            border-bottom: 1px solid #e8e8e8;
            background-color: #fff;
        }}
        .bby-table tr:hover td {{
            background-color: #f5fbfb;
        }}
    </style>
    <table class="bby-table">
        <thead>
            <tr>
                <th style="width:80px;">Image</th>
                <th>Product</th>
                <th style="width:160px;">Price</th>
                <th style="width:110px;">Availability</th>
                <th style="width:130px;">Pulled At</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    """
    return table_html

def show_results(df: pd.DataFrame):
    n_verify = int(df["verify_price"].sum()) if "verify_price" in df.columns else 0
    st.success(f"Found {len(df)} products.")
    if n_verify:
        st.warning(
            f"⚠️ {n_verify} item(s) show the same sale and regular price in the API — "
            "Best Buy may still have an active promo on the site. Click the product link to confirm."
        )

    # HTML table with images and links
    st.markdown(render_html_table(df), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # CSV export (drop image column for cleanliness, keep url as plain text)
    csv_df = df.drop(columns=["image"], errors="ignore")
    st.download_button(
        "⬇️ Download CSV",
        csv_df.to_csv(index=False),
        "products.csv",
        "text/csv"
    )

# ------------------------
# UI
# ------------------------
st.title("Best Buy Product Explorer")

st.sidebar.markdown("""
**ℹ️ Price note**

Most sale prices are captured from the API.
Items marked **⚠️ Check site for promos** have matching sale/regular prices
in the API — Best Buy's internal pricing engine may still apply a discount
that isn't exposed via the public API. Click the product link to confirm.
""")

mode = st.sidebar.radio("Choose an input method:", ("SKU List", "Keyword Search", "Category Browse"))

if mode == "SKU List":
    st.subheader("Search by SKU list")
    sku_input = st.text_area(
        "Paste SKUs (commas, spaces, tabs, or one-per-line — Excel paste works too):",
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
                show_results(df)

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
                show_results(df)

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
                show_results(df)

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

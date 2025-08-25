import streamlit as st
import requests
import pandas as pd
import time
import datetime

# --- Streamlit page config ---
st.set_page_config(page_title="Best Buy Product Explorer", layout="wide")

# Load API key from Streamlit secrets
API_KEY = st.secrets["BESTBUY_API_KEY"]
BASE_URL = "https://api.bestbuy.com/v1"

# --- Helper functions ---
def fetch_products(query, mode="keyword", page=1, page_size=20):
    params = {
        "apiKey": API_KEY,
        "format": "json",
        "show": "sku,name,regularPrice,salePrice,onlineAvailability,modelNumber,manufacturer,categoryPath.name",
        "pageSize": page_size,
        "page": page
    }

    if mode == "keyword":
        url = f"{BASE_URL}/products((search={query}))"
    elif mode == "category":
        url = f"{BASE_URL}/products((categoryPath.id={query}))"
    else:
        return []

    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get("products", [])
    else:
        st.error(f"Error {response.status_code}: {response.text}")
        return []

def fetch_sku_list(sku_list):
    products = []
    chunk_size = 100  # Best Buy API max
    for i in range(0, len(sku_list), chunk_size):
        chunk = ",".join(sku_list[i:i+chunk_size])
        url = f"{BASE_URL}/products(sku in({chunk}))"
        params = {
            "apiKey": API_KEY,
            "format": "json",
            "show": "sku,name,regularPrice,salePrice,onlineAvailability,categoryPath.name,modelNumber,manufacturer",
            "pageSize": 100
        }
        retries = 8
        for attempt in range(retries):
            response = requests.get(url, params=params)
            if response.status_code == 200:
                products.extend(response.json().get("products", []))
                break
            elif response.status_code == 403:
                st.warning("Rate limit hit. Retrying...")
                time.sleep(1.5 * (attempt + 1))  # exponential backoff
            else:
                st.error(f"Error {response.status_code}: {response.text}")
                break
        time.sleep(0.3)  # prevent hitting per-second limit
    return products



def fetch_categories():
    url = f"{BASE_URL}/categories"
    params = {
        "apiKey": API_KEY,
        "format": "json",
        "show": "id,name",
        "pageSize": 100
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get("categories", [])
    return []

# --- Streamlit UI ---
st.title("🛒 Best Buy Product Explorer v1.1")

mode = st.radio("Choose Input Mode:", ["SKU List", "Keyword Search", "Category Browse"])

if mode == "SKU List":
    st.write("Upload CSV or paste SKUs (comma-separated or line-separated):")
    sku_input = st.text_area("Enter SKUs:")
    if st.button("Fetch SKU Details"):
        if sku_input:
            sku_list = sku_input.replace("\n", ",").split(",")
            sku_list = [s.strip() for s in sku_list if s.strip()]
            products = fetch_sku_list(sku_list)   # chunked fetch with progress
            if products:
                df = pd.DataFrame(products)

                # Flatten categoryPath.name into a single column
                if "categoryPath" in df.columns:
                    df["categories"] = df["categoryPath"].apply(lambda x: " > ".join([c["name"] for c in x]) if isinstance(x, list) else "")
                    df.drop(columns=["categoryPath"], inplace=True)

                # ✅ Add timestamp column to results
                if results:
                    df = pd.DataFrame(products)
                    df["data_pull_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    return df
                return pd.DataFrame()

                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "sku_results.csv", "text/csv")
            else:
                st.warning("No products found.")
        else:
            st.warning("Please enter at least one SKU.")

elif mode == "Keyword Search":
    keyword = st.text_input("Enter keyword (e.g., laptop, TV, headphones):")
    if st.button("Search"):
        if keyword:
            products = fetch_products(keyword, mode="keyword", page_size=50)
            if products:
                df = pd.DataFrame(products)
                if "categoryPath" in df.columns:
                    df["categories"] = df["categoryPath"].apply(lambda x: " > ".join([c["name"] for c in x]) if isinstance(x, list) else "")
                    df.drop(columns=["categoryPath"], inplace=True)
                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "keyword_results.csv", "text/csv")
        else:
            st.warning("Please enter a keyword.")

elif mode == "Category Browse":
    categories = fetch_categories()
    if categories:
        category_map = {c["name"]: c["id"] for c in categories}
        category_name = st.selectbox("Choose a category:", list(category_map.keys()))
        if st.button("Browse Category"):
            category_id = category_map[category_name]
            products = fetch_products(category_id, mode="category", page_size=50)
            if products:
                df = pd.DataFrame(products)
                if "categoryPath" in df.columns:
                    df["categories"] = df["categoryPath"].apply(lambda x: " > ".join([c["name"] for c in x]) if isinstance(x, list) else "")
                    df.drop(columns=["categoryPath"], inplace=True)
                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "category_results.csv", "text/csv")

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

    

import streamlit as st
import requests
import pandas as pd
import datetime
import time

# Best Buy API Key (stored in Streamlit Secrets)
API_KEY = st.secrets["BESTBUY_API_KEY"]

BASE_URL = "https://api.bestbuy.com/v1"

# ------------------------
# Helper functions
# ------------------------
def fetch_products_by_skus(skus):
    results = []
    progress_bar = st.progress(0)

    for i, sku in enumerate(skus):
        url = f"{BASE_URL}/products(sku={sku})?apiKey={API_KEY}&format=json"
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if "products" in data and len(data["products"]) > 0:
                product = data["products"][0]
                results.append({
                    "sku": product.get("sku"),
                    "name": product.get("name"),
                    "modelNumber": product.get("modelNumber"),
                    "brand": product.get("manufacturer"),
                    "category": product.get("class", {}).get("name") if "class" in product else None,
                    "regularPrice": product.get("regularPrice"),
                    "salePrice": product.get("salePrice"),
                    "url": product.get("url")
                })
        # update progress
        progress_bar.progress((i + 1) / len(skus))
        time.sleep(0.2)  # prevent rate limiting

    # ✅ Add timestamp column to results
    if results:
        df = pd.DataFrame(results)
        df["data_pull_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df

    return pd.DataFrame()


def fetch_products_by_keyword(keyword):
    url = f"{BASE_URL}/products((search={keyword}))?apiKey={API_KEY}&format=json"
    resp = requests.get(url)
    results = []

    if resp.status_code == 200:
        data = resp.json()
        for product in data.get("products", []):
            results.append({
                "sku": product.get("sku"),
                "name": product.get("name"),
                "modelNumber": product.get("modelNumber"),
                "brand": product.get("manufacturer"),
                "category": product.get("class", {}).get("name") if "class" in product else None,
                "regularPrice": product.get("regularPrice"),
                "salePrice": product.get("salePrice"),
                "url": product.get("url")
            })

    # ✅ Add timestamp
    if results:
        df = pd.DataFrame(results)
        df["data_pull_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df

    return pd.DataFrame()


def fetch_products_by_category(category_id):
    url = f"{BASE_URL}/products(categoryPath.id={category_id})?apiKey={API_KEY}&format=json"
    resp = requests.get(url)
    results = []

    if resp.status_code == 200:
        data = resp.json()
        for product in data.get("products", []):
            results.append({
                "sku": product.get("sku"),
                "name": product.get("name"),
                "modelNumber": product.get("modelNumber"),
                "brand": product.get("manufacturer"),
                "category": product.get("class", {}).get("name") if "class" in product else None,
                "regularPrice": product.get("regularPrice"),
                "salePrice": product.get("salePrice"),
                "url": product.get("url")
            })

    # ✅ Add timestamp
    if results:
        df = pd.DataFrame(results)
        df["data_pull_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df

    return pd.DataFrame()


# ------------------------
# Streamlit UI
# ------------------------
st.title("Best Buy Product Explorer")

option = st.sidebar.radio("Choose an input method:", ("SKU List", "Keyword Search", "Category Browse"))

if option == "SKU List":
    sku_input = st.text_area("Enter SKUs (comma-separated)")
    if st.button("Fetch by SKUs"):
        skus = [s.strip() for s in sku_input.split(",") if s.strip()]
        if skus:
            df = fetch_products_by_skus(skus)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "products.csv", "text/csv")
            else:
                st.warning("No products found.")

elif option == "Keyword Search":
    keyword = st.text_input("Enter a keyword")
    if st.button("Search"):
        if keyword:
            df = fetch_products_by_keyword(keyword)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "products.csv", "text/csv")
            else:
                st.warning("No products found.")

elif option == "Category Browse":
    category_id = st.text_input("Enter a category ID")
    if st.button("Browse Category"):
        if category_id:
            df = fetch_products_by_category(category_id)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                st.download_button("Download CSV", df.to_csv(index=False), "products.csv", "text/csv")
            else:
                st.warning("No products found.")


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

    

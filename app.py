import streamlit as st
import requests
import pandas as pd

# Load API key from Streamlit secrets
API_KEY = st.secrets["BESTBUY_API_KEY"]
BASE_URL = "https://api.bestbuy.com/v1"

# --- Helper functions ---
def fetch_products(query, mode="keyword", page=1, page_size=20):
    params = {
        "apiKey": API_KEY,
        "format": "json",
        "show": "sku,name,regularPrice,salePrice,onlineAvailability",
        "pageSize": page_size,
        "page": page
    }

    if mode == "keyword":
        url = f"{BASE_URL}/products((search={query}))"
    elif mode == "sku":
        url = f"{BASE_URL}/products(sku in({query}))"
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
st.title("🛒 Best Buy Product Explorer")

mode = st.radio("Choose Input Mode:", ["SKU List", "Keyword Search", "Category Browse"])

if mode == "SKU List":
    st.write("Upload CSV or paste SKUs (comma-separated):")
    sku_input = st.text_area("Enter SKUs:")
    if st.button("Fetch SKU Details"):
        if sku_input:
            sku_list = sku_input.replace("\n", ",").split(",")
            products = fetch_products(",".join(sku_list), mode="sku")
            if products:
                df = pd.DataFrame(products)
                st.dataframe(df)
                st.download_button("Download CSV", df.to_csv(index=False), "sku_results.csv", "text/csv")
        else:
            st.warning("Please enter at least one SKU.")

elif mode == "Keyword Search":
    keyword = st.text_input("Enter keyword (e.g., laptop, TV, headphones):")
    if st.button("Search"):
        if keyword:
            products = fetch_products(keyword, mode="keyword")
            if products:
                df = pd.DataFrame(products)
                st.dataframe(df)
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
            products = fetch_products(category_id, mode="category")
            if products:
                df = pd.DataFrame(products)
                st.dataframe(df)
                st.download_button("Download CSV", df.to_csv(index=False), "category_results.csv", "text/csv")

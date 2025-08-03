
import streamlit as st
import sqlite3
import requests
import cv2
import numpy as np
import pyzbar
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image
import io
import base64

# Database setup
def init_database():
    conn = sqlite3.connect('pantry_inventory.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE,
            product_name TEXT,
            brand TEXT,
            quantity INTEGER DEFAULT 1,
            unit TEXT DEFAULT 'item',
            date_added TEXT,
            expiry_date TEXT,
            image_url TEXT,
            category TEXT,
            last_updated TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Product lookup using Open Food Facts API
def lookup_product(barcode):
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 1:
                product = data.get('product', {})
                return {
                    'name': product.get('product_name', 'Unknown Product'),
                    'brand': product.get('brands', 'Unknown Brand'),
                    'image_url': product.get('image_url', ''),
                    'category': product.get('categories', 'Unknown Category')
                }
    except Exception as e:
        st.error(f"Error looking up product: {str(e)}")
    
    return None

# Database operations
def add_to_inventory(barcode, product_info, quantity=1, expiry_date=None):
    conn = sqlite3.connect('pantry_inventory.db')
    c = conn.cursor()
    
    current_time = datetime.now().isoformat()
    
    # Check if item already exists
    c.execute("SELECT quantity FROM inventory WHERE barcode = ?", (barcode,))
    existing = c.fetchone()
    
    if existing:
        # Update quantity
        new_quantity = existing[0] + quantity
        c.execute("""
            UPDATE inventory 
            SET quantity = ?, last_updated = ?
            WHERE barcode = ?
        """, (new_quantity, current_time, barcode))
        st.success(f"Updated quantity to {new_quantity}")
    else:
        # Add new item
        c.execute("""
            INSERT INTO inventory 
            (barcode, product_name, brand, quantity, date_added, expiry_date, 
             image_url, category, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            barcode,
            product_info.get('name', 'Unknown Product'),
            product_info.get('brand', 'Unknown Brand'),
            quantity,
            current_time,
            expiry_date,
            product_info.get('image_url', ''),
            product_info.get('category', 'Unknown Category'),
            current_time
        ))
        st.success("Added new item to inventory!")
    
    conn.commit()
    conn.close()

def remove_from_inventory(barcode, quantity=1):
    conn = sqlite3.connect('pantry_inventory.db')
    c = conn.cursor()
    
    c.execute("SELECT quantity, product_name FROM inventory WHERE barcode = ?", (barcode,))
    result = c.fetchone()
    
    if result:
        current_qty, product_name = result
        new_quantity = max(0, current_qty - quantity)
        
        current_time = datetime.now().isoformat()
        c.execute("""
            UPDATE inventory 
            SET quantity = ?, last_updated = ?
            WHERE barcode = ?
        """, (new_quantity, current_time, barcode))
        
        conn.commit()
        
        if new_quantity == 0:
            st.warning(f"{product_name} is now out of stock!")
        else:
            st.success(f"Used {quantity} {product_name}. {new_quantity} remaining.")
    else:
        st.error("Item not found in inventory!")
    
    conn.close()

def get_inventory():
    conn = sqlite3.connect('pantry_inventory.db')
    df = pd.read_sql_query("SELECT * FROM inventory ORDER BY last_updated DESC", conn)
    conn.close()
    return df

# Barcode scanning functions
def decode_barcode_from_image(image):
    """Decode barcode from image array"""
    # Convert PIL image to OpenCV format
    if isinstance(image, Image.Image):
        image = np.array(image)
    
    # Convert RGB to BGR for OpenCV
    if len(image.shape) == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    
    # Decode barcodes
    barcodes = pyzbar.decode(image)
    
    if barcodes:
        return barcodes[0].data.decode('utf-8')
    return None

# Streamlit UI
def main():
    st.set_page_config(
        page_title="Pantry Inventory Tracker",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize database
    init_database()
    
    st.title("🏠 Pantry Inventory Tracker")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Choose Action",
        ["📱 Scan Barcode", "📦 View Inventory", "➕ Manual Add", "📊 Statistics"]
    )
    
    if page == "📱 Scan Barcode":
        st.header("Scan Item Barcode")
        
        # Action selection
        action = st.radio(
            "What do you want to do?",
            ["Add to Inventory", "Use from Inventory"],
            horizontal=True
        )
        
        # Camera input
        st.subheader("Take a photo of the barcode")
        camera_image = st.camera_input("Capture barcode")
        
        # Manual barcode input as fallback
        manual_barcode = st.text_input("Or enter barcode manually:")
        
        barcode = None
        
        if camera_image is not None:
            # Process camera image
            image = Image.open(camera_image)
            st.image(image, caption="Captured Image", width=300)
            
            # Decode barcode
            barcode = decode_barcode_from_image(image)
            if barcode:
                st.success(f"Barcode detected: {barcode}")
            else:
                st.error("No barcode detected. Try taking another photo or enter manually.")
        
        if manual_barcode:
            barcode = manual_barcode
            st.info(f"Using manual barcode: {barcode}")
        
        if barcode:
            if action == "Add to Inventory":
                st.subheader("Add Item to Inventory")
                
                # Lookup product information
                with st.spinner("Looking up product information..."):
                    product_info = lookup_product(barcode)
                
                if product_info:
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.write(f"**Product:** {product_info['name']}")
                        st.write(f"**Brand:** {product_info['brand']}")
                        st.write(f"**Category:** {product_info['category']}")
                    
                    with col2:
                        if product_info.get('image_url'):
                            try:
                                st.image(product_info['image_url'], width=150)
                            except:
                                st.write("Image not available")
                    
                    # Quantity and expiry inputs
                    col1, col2 = st.columns(2)
                    with col1:
                        quantity = st.number_input("Quantity to add:", min_value=1, value=1)
                    with col2:
                        expiry_date = st.date_input("Expiry date (optional):")
                    
                    if st.button("Add to Inventory", type="primary"):
                        expiry_str = expiry_date.isoformat() if expiry_date else None
                        add_to_inventory(barcode, product_info, quantity, expiry_str)
                        st.rerun()
                else:
                    st.warning("Product not found in database. You can still add it manually.")
                    product_name = st.text_input("Product Name:")
                    brand = st.text_input("Brand:")
                    quantity = st.number_input("Quantity:", min_value=1, value=1)
                    
                    if st.button("Add to Inventory") and product_name:
                        product_info = {
                            'name': product_name,
                            'brand': brand,
                            'image_url': '',
                            'category': 'Manual Entry'
                        }
                        add_to_inventory(barcode, product_info, quantity)
                        st.rerun()
            
            elif action == "Use from Inventory":
                st.subheader("Use Item from Inventory")
                
                # Check if item exists in inventory
                conn = sqlite3.connect('pantry_inventory.db')
                c = conn.cursor()
                c.execute("SELECT product_name, quantity FROM inventory WHERE barcode = ?", (barcode,))
                result = c.fetchone()
                conn.close()
                
                if result:
                    product_name, current_quantity = result
                    st.write(f"**Product:** {product_name}")
                    st.write(f"**Current Quantity:** {current_quantity}")
                    
                    use_quantity = st.number_input(
                        "Quantity to use:", 
                        min_value=1, 
                        max_value=current_quantity, 
                        value=1
                    )
                    
                    if st.button("Use Item", type="primary"):
                        remove_from_inventory(barcode, use_quantity)
                        st.rerun()
                else:
                    st.error("Item not found in inventory!")
    
    elif page == "📦 View Inventory":
        st.header("Current Inventory")
        
        df = get_inventory()
        
        if not df.empty:
            # Summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Items", len(df))
            with col2:
                st.metric("Low Stock Items", len(df[df['quantity'] <= 2]))
            with col3:
                st.metric("Out of Stock", len(df[df['quantity'] == 0]))
            
            # Filter options
            st.subheader("Filters")
            col1, col2 = st.columns(2)
            with col1:
                show_empty = st.checkbox("Show out of stock items")
            with col2:
                category_filter = st.selectbox(
                    "Filter by category:",
                    ["All"] + list(df['category'].unique())
                )
            
            # Apply filters
            filtered_df = df.copy()
            if not show_empty:
                filtered_df = filtered_df[filtered_df['quantity'] > 0]
            if category_filter != "All":
                filtered_df = filtered_df[filtered_df['category'] == category_filter]
            
            # Display inventory
            for _, item in filtered_df.iterrows():
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        st.write(f"**{item['product_name']}**")
                        st.write(f"Brand: {item['brand']}")
                        if item['expiry_date']:
                            expiry = datetime.fromisoformat(item['expiry_date'])
                            days_to_expiry = (expiry.date() - datetime.now().date()).days
                            if days_to_expiry < 0:
                                st.error(f"Expired {abs(days_to_expiry)} days ago")
                            elif days_to_expiry <= 7:
                                st.warning(f"Expires in {days_to_expiry} days")
                    
                    with col2:
                        st.metric("Quantity", item['quantity'])
                    
                    with col3:
                        if item['image_url']:
                            try:
                                st.image(item['image_url'], width=80)
                            except:
                                st.write("📦")
                        else:
                            st.write("📦")
                    
                    with col4:
                        if st.button(f"Remove", key=f"remove_{item['id']}"):
                            remove_from_inventory(item['barcode'], 1)
                            st.rerun()
                    
                    st.divider()
        else:
            st.info("Your inventory is empty. Start by scanning some items!")
    
    elif page == "➕ Manual Add":
        st.header("Manually Add Item")
        
        with st.form("manual_add_form"):
            barcode = st.text_input("Barcode:")
            product_name = st.text_input("Product Name:")
            brand = st.text_input("Brand:")
            quantity = st.number_input("Quantity:", min_value=1, value=1)
            category = st.text_input("Category:")
            expiry_date = st.date_input("Expiry Date (optional):")
            
            submitted = st.form_submit_button("Add to Inventory")
            
            if submitted and barcode and product_name:
                product_info = {
                    'name': product_name,
                    'brand': brand,
                    'image_url': '',
                    'category': category or 'Manual Entry'
                }
                expiry_str = expiry_date.isoformat() if expiry_date else None
                add_to_inventory(barcode, product_info, quantity, expiry_str)
                st.success("Item added successfully!")
    
    elif page == "📊 Statistics":
        st.header("Inventory Statistics")
        
        df = get_inventory()
        
        if not df.empty:
            # Category breakdown
            st.subheader("Items by Category")
            category_counts = df['category'].value_counts()
            st.bar_chart(category_counts)
            
            # Low stock alerts
            st.subheader("Low Stock Alerts")
            low_stock = df[df['quantity'] <= 2]
            if not low_stock.empty:
                for _, item in low_stock.iterrows():
                    if item['quantity'] == 0:
                        st.error(f"OUT OF STOCK: {item['product_name']}")
                    else:
                        st.warning(f"LOW STOCK: {item['product_name']} ({item['quantity']} remaining)")
            else:
                st.success("All items are well stocked!")
            
            # Expiry alerts
            st.subheader("Expiry Alerts")
            expiring_soon = []
            expired = []
            
            for _, item in df.iterrows():
                if item['expiry_date']:
                    expiry = datetime.fromisoformat(item['expiry_date'])
                    days_to_expiry = (expiry.date() - datetime.now().date()).days
                    
                    if days_to_expiry < 0:
                        expired.append((item['product_name'], abs(days_to_expiry)))
                    elif days_to_expiry <= 7:
                        expiring_soon.append((item['product_name'], days_to_expiry))
            
            if expired:
                st.error("Expired Items:")
                for name, days in expired:
                    st.write(f"• {name} (expired {days} days ago)")
            
            if expiring_soon:
                st.warning("Expiring Soon:")
                for name, days in expiring_soon:
                    st.write(f"• {name} (expires in {days} days)")
            
            if not expired and not expiring_soon:
                st.success("No items expiring soon!")
        else:
            st.info("No data available yet. Add some items to see statistics!")

if __name__ == "__main__":
    main()
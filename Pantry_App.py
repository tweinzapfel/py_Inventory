import streamlit as st
import sqlite3
import requests
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    PYZBAR_AVAILABLE = True
except ImportError:
    try:
        from pyzbar import decode as pyzbar_decode
        PYZBAR_AVAILABLE = True
    except ImportError:
        PYZBAR_AVAILABLE = False
        pyzbar_decode = None
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
    if not PYZBAR_AVAILABLE:
        st.error("🚫 Barcode scanning library (pyzbar) is not available.")
        return None
    
    try:
        # Try without OpenCV first - pyzbar can work with PIL images directly
        if isinstance(image, Image.Image):
            # Convert PIL image to numpy array
            if NUMPY_AVAILABLE:
                image_array = np.array(image)
            else:
                # Fallback: try direct PIL image processing
                barcodes = pyzbar_decode(image)
                if barcodes:
                    return barcodes[0].data.decode('utf-8')
                return None
        else:
            image_array = image
        
        # If we have OpenCV, use it for better preprocessing
        if CV2_AVAILABLE and NUMPY_AVAILABLE:
            # Convert RGB to BGR for OpenCV
            if len(image_array.shape) == 3:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            
            # Try to enhance the image for better barcode detection
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            
            # Try different preprocessing techniques
            images_to_try = [
                image_array,  # Original
                gray,         # Grayscale
            ]
            
            # Try adaptive threshold if possible
            try:
                thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                images_to_try.append(thresh)
            except:
                pass
        else:
            # Without OpenCV, just try the numpy array
            images_to_try = [image_array] if NUMPY_AVAILABLE else []
        
        # Try to decode barcode from each preprocessed image
        for img in images_to_try:
            try:
                barcodes = pyzbar_decode(img)
                if barcodes:
                    return barcodes[0].data.decode('utf-8')
            except Exception as e:
                continue
        
        # If all else fails, try the original PIL image
        if isinstance(image, Image.Image):
            try:
                barcodes = pyzbar_decode(image)
                if barcodes:
                    return barcodes[0].data.decode('utf-8')
            except:
                pass
                
    except Exception as e:
        st.error(f"❌ Error decoding barcode: {str(e)}")
        st.info("💡 Try using manual barcode entry instead.")
    
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
    
    # Main tab navigation
    tab1, tab2, tab3, tab4 = st.tabs(["📦 Current Inventory", "➕ Add Items", "➖ Use Items", "📊 Statistics"])
    
    with tab1:
        st.header("Your Pantry Inventory")
        
        df = get_inventory()
        
        if not df.empty:
            # Summary stats at top
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Items", len(df[df['quantity'] > 0]))
            with col2:
                st.metric("Total Products", len(df))
            with col3:
                st.metric("Low Stock", len(df[df['quantity'] <= 2]))
            with col4:
                st.metric("Out of Stock", len(df[df['quantity'] == 0]))
            
            st.divider()
            
            # Filter options
            col1, col2, col3 = st.columns(3)
            with col1:
                show_empty = st.checkbox("Show out of stock items", value=True)
            with col2:
                category_filter = st.selectbox(
                    "Filter by category:",
                    ["All"] + sorted(list(df['category'].unique()))
                )
            with col3:
                sort_by = st.selectbox(
                    "Sort by:",
                    ["Last Updated", "Product Name", "Quantity", "Expiry Date"]
                )
            
            # Apply filters
            filtered_df = df.copy()
            if not show_empty:
                filtered_df = filtered_df[filtered_df['quantity'] > 0]
            if category_filter != "All":
                filtered_df = filtered_df[filtered_df['category'] == category_filter]
            
            # Apply sorting
            if sort_by == "Product Name":
                filtered_df = filtered_df.sort_values('product_name')
            elif sort_by == "Quantity":
                filtered_df = filtered_df.sort_values('quantity', ascending=False)
            elif sort_by == "Expiry Date":
                filtered_df = filtered_df.sort_values('expiry_date', na_last=True)
            else:  # Last Updated
                filtered_df = filtered_df.sort_values('last_updated', ascending=False)
            
            st.subheader(f"Items ({len(filtered_df)})")
            
            # Display inventory in a more organized way
            if len(filtered_df) > 0:
                for _, item in filtered_df.iterrows():
                    with st.container():
                        col1, col2, col3, col4, col5 = st.columns([4, 1, 1, 1, 1])
                        
                        with col1:
                            # Product name and brand
                            if item['quantity'] == 0:
                                st.markdown(f"**{item['product_name']}** ⚠️ *OUT OF STOCK*")
                            elif item['quantity'] <= 2:
                                st.markdown(f"**{item['product_name']}** ⚠️ *LOW STOCK*")
                            else:
                                st.markdown(f"**{item['product_name']}**")
                            
                            st.caption(f"Brand: {item['brand']} | Category: {item['category']}")
                            
                            # Expiry information
                            if item['expiry_date']:
                                try:
                                    expiry = datetime.fromisoformat(item['expiry_date'])
                                    days_to_expiry = (expiry.date() - datetime.now().date()).days
                                    if days_to_expiry < 0:
                                        st.error(f"🚨 Expired {abs(days_to_expiry)} days ago")
                                    elif days_to_expiry <= 7:
                                        st.warning(f"⏰ Expires in {days_to_expiry} days")
                                    else:
                                        st.info(f"📅 Expires: {expiry.strftime('%m/%d/%Y')}")
                                except:
                                    pass
                        
                        with col2:
                            # Quantity with color coding
                            if item['quantity'] == 0:
                                st.metric("Qty", "0", delta=None)
                            elif item['quantity'] <= 2:
                                st.metric("Qty", item['quantity'], delta="Low")
                            else:
                                st.metric("Qty", item['quantity'])
                        
                        with col3:
                            # Product image
                            if item['image_url']:
                                try:
                                    st.image(item['image_url'], width=60)
                                except:
                                    st.markdown("📦")
                            else:
                                st.markdown("📦")
                        
                        with col4:
                            # Quick add button
                            if st.button("➕", key=f"add_{item['id']}", help="Add one more"):
                                add_to_inventory(item['barcode'], {
                                    'name': item['product_name'],
                                    'brand': item['brand'],
                                    'image_url': item['image_url'],
                                    'category': item['category']
                                }, 1)
                                st.rerun()
                        
                        with col5:
                            # Quick use button
                            if item['quantity'] > 0:
                                if st.button("➖", key=f"use_{item['id']}", help="Use one"):
                                    remove_from_inventory(item['barcode'], 1)
                                    st.rerun()
                            else:
                                st.write("")
                        
                        st.divider()
            else:
                st.info("No items match your current filters.")
        else:
            st.info("🛒 Your pantry is empty! Use the 'Add Items' tab to start tracking your inventory.")
            st.markdown("### Get Started:")
            st.markdown("- Use the **Add Items** tab to scan barcodes or manually add products")
            st.markdown("- Use the **Use Items** tab when you consume something from your pantry")
    
    with tab2:
        st.header("Add Items to Inventory")
        
        # Method selection
        add_method = st.radio(
            "How would you like to add items?",
            ["📱 Scan Barcode", "✏️ Manual Entry"],
            horizontal=True
        )
        
        if add_method == "📱 Scan Barcode":
            st.subheader("Scan Item Barcode")
            
            # Show library status
            if not PYZBAR_AVAILABLE:
                st.error("🚫 Barcode scanning library (pyzbar) is not available.")
                st.info("💡 Please use manual barcode entry below.")
            elif not CV2_AVAILABLE:
                st.warning("⚠️ Advanced image processing unavailable (OpenCV missing).")
                st.info("📸 Basic barcode scanning may still work. If not, use manual entry.")
            else:
                st.success("✅ All barcode scanning libraries are available!")
            
            # Camera input (show even if libraries unavailable for testing)
            st.write("Take a photo of the barcode:")
            camera_image = st.camera_input("Capture barcode", key="add_camera")
            
            # Manual barcode input as fallback
            manual_barcode = st.text_input("Or enter barcode manually:", key="add_manual_barcode", 
                                         help="Type the numbers from the barcode here")
            
            barcode = None
            
            if camera_image is not None:
                # Process camera image
                image = Image.open(camera_image)
                st.image(image, caption="Captured Image", width=300)
                
                if PYZBAR_AVAILABLE:
                    with st.spinner("🔍 Scanning for barcode..."):
                        # Decode barcode
                        barcode = decode_barcode_from_image(image)
                        if barcode:
                            st.success(f"✅ Barcode detected: {barcode}")
                        else:
                            st.warning("❌ No barcode detected in image.")
                            st.info("💡 Try:\n- Taking a clearer photo\n- Getting closer to the barcode\n- Ensuring good lighting\n- Using manual entry below")
                else:
                    st.info("📝 Barcode scanning unavailable. Please enter the barcode number manually below.")
            
            if manual_barcode:
                barcode = manual_barcode
                st.info(f"Using barcode: {barcode}")
            
            if barcode:
                st.subheader("Product Information")
                
                # Lookup product information
                with st.spinner("🔍 Looking up product information..."):
                    product_info = lookup_product(barcode)
                
                if product_info:
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.success("✅ Product found!")
                        st.write(f"**Product:** {product_info['name']}")
                        st.write(f"**Brand:** {product_info['brand']}")
                        st.write(f"**Category:** {product_info['category']}")
                    
                    with col2:
                        if product_info.get('image_url'):
                            try:
                                st.image(product_info['image_url'], width=150)
                            except:
                                st.write("📦")
                    
                    # Quantity and expiry inputs
                    col1, col2 = st.columns(2)
                    with col1:
                        quantity = st.number_input("Quantity to add:", min_value=1, value=1, key="scan_quantity")
                    with col2:
                        expiry_date = st.date_input("Expiry date (optional):", value=None, key="scan_expiry")
                    
                    if st.button("🛒 Add to Inventory", type="primary", key="scan_add_btn"):
                        expiry_str = expiry_date.isoformat() if expiry_date else None
                        add_to_inventory(barcode, product_info, quantity, expiry_str)
                        st.rerun()
                else:
                    st.warning("⚠️ Product not found in database. You can add it manually below:")
                    with st.form("unknown_product_form"):
                        product_name = st.text_input("Product Name:", key="unknown_name")
                        brand = st.text_input("Brand:", key="unknown_brand")
                        category = st.text_input("Category:", key="unknown_category")
                        quantity = st.number_input("Quantity:", min_value=1, value=1, key="unknown_quantity")
                        expiry_date = st.date_input("Expiry Date (optional):", value=None, key="unknown_expiry")
                        
                        submitted = st.form_submit_button("🛒 Add to Inventory", type="primary")
                        
                        if submitted and product_name:
                            product_info = {
                                'name': product_name,
                                'brand': brand or 'Unknown Brand',
                                'image_url': '',
                                'category': category or 'Unknown Category'
                            }
                            expiry_str = expiry_date.isoformat() if expiry_date else None
                            add_to_inventory(barcode, product_info, quantity, expiry_str)
                            st.success("✅ Item added successfully!")
                            st.rerun()
        
        else:  # Manual Entry
            st.subheader("Manual Product Entry")
            
            with st.form("manual_add_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    barcode = st.text_input("Barcode:", help="Enter the barcode number")
                    product_name = st.text_input("Product Name:")
                    brand = st.text_input("Brand:")
                
                with col2:
                    category = st.text_input("Category:", placeholder="e.g., Snacks, Beverages, Dairy")
                    quantity = st.number_input("Quantity:", min_value=1, value=1)
                    expiry_date = st.date_input("Expiry Date (optional):", value=None)
                
                submitted = st.form_submit_button("🛒 Add to Inventory", type="primary")
                
                if submitted:
                    if barcode and product_name:
                        product_info = {
                            'name': product_name,
                            'brand': brand or 'Unknown Brand',
                            'image_url': '',
                            'category': category or 'Manual Entry'
                        }
                        expiry_str = expiry_date.isoformat() if expiry_date else None
                        add_to_inventory(barcode, product_info, quantity, expiry_str)
                        st.success("✅ Item added successfully!")
                        st.rerun()
                    else:
                        st.error("❌ Please enter both barcode and product name.")
    
    with tab3:
        st.header("Use Items from Inventory")
        
        # Method selection
        use_method = st.radio(
            "How would you like to select items?",
            ["📱 Scan Barcode", "📋 Select from List"],
            horizontal=True
        )
        
        if use_method == "📱 Scan Barcode":
            st.subheader("Scan Item Barcode")
            
            # Show library status
            if not PYZBAR_AVAILABLE:
                st.error("🚫 Barcode scanning library (pyzbar) is not available.")
                st.info("💡 Please use 'Select from List' option above or manual barcode entry below.")
            elif not CV2_AVAILABLE:
                st.warning("⚠️ Advanced image processing unavailable (OpenCV missing).")
                st.info("📸 Basic barcode scanning may still work. If not, use 'Select from List' or manual entry.")
            
            # Camera input
            st.write("Take a photo of the barcode:")
            camera_image = st.camera_input("Capture barcode", key="use_camera")
            
            # Manual barcode input as fallback
            manual_barcode = st.text_input("Or enter barcode manually:", key="use_manual_barcode",
                                         help="Type the numbers from the barcode here")
            
            barcode = None
            
            if camera_image is not None:
                # Process camera image
                image = Image.open(camera_image)
                st.image(image, caption="Captured Image", width=300)
                
                if PYZBAR_AVAILABLE:
                    with st.spinner("🔍 Scanning for barcode..."):
                        # Decode barcode
                        barcode = decode_barcode_from_image(image)
                        if barcode:
                            st.success(f"✅ Barcode detected: {barcode}")
                        else:
                            st.warning("❌ No barcode detected in image.")
                            st.info("💡 Try using 'Select from List' above or manual entry below.")
                else:
                    st.info("📝 Barcode scanning unavailable. Please use 'Select from List' above or enter manually below.")
            
            if manual_barcode:
                barcode = manual_barcode
                st.info(f"Using barcode: {barcode}")
            
            if barcode:
                st.subheader("Use Item from Inventory")
                
                # Check if item exists in inventory
                conn = sqlite3.connect('pantry_inventory.db')
                c = conn.cursor()
                c.execute("SELECT product_name, quantity FROM inventory WHERE barcode = ?", (barcode,))
                result = c.fetchone()
                conn.close()
                
                if result:
                    product_name, current_quantity = result
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.success(f"✅ Found: **{product_name}**")
                        st.write(f"**Current Stock:** {current_quantity}")
                    
                    if current_quantity > 0:
                        use_quantity = st.number_input(
                            "Quantity to use:", 
                            min_value=1, 
                            max_value=current_quantity, 
                            value=1,
                            key="scan_use_quantity"
                        )
                        
                        if st.button("✅ Use Item", type="primary", key="scan_use_btn"):
                            remove_from_inventory(barcode, use_quantity)
                            st.rerun()
                    else:
                        st.error("❌ This item is out of stock!")
                else:
                    st.error("❌ Item not found in inventory!")
        
        else:  # Select from List
            st.subheader("Select Item from Your Inventory")
            
            df = get_inventory()
            available_items = df[df['quantity'] > 0]
            
            if not available_items.empty:
                # Create a selectbox with available items
                item_options = {}
                for _, item in available_items.iterrows():
                    display_name = f"{item['product_name']} ({item['brand']}) - Stock: {item['quantity']}"
                    item_options[display_name] = {
                        'barcode': item['barcode'],
                        'name': item['product_name'],
                        'quantity': item['quantity']
                    }
                
                selected_display = st.selectbox(
                    "Choose an item to use:",
                    options=list(item_options.keys()),
                    key="list_select_item"
                )
                
                if selected_display:
                    selected_item = item_options[selected_display]
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        use_quantity = st.number_input(
                            "Quantity to use:",
                            min_value=1,
                            max_value=selected_item['quantity'],
                            value=1,
                            key="list_use_quantity"
                        )
                    
                    with col2:
                        st.write("")  # Empty space for alignment
                        st.write("")  # Empty space for alignment
                        if st.button("✅ Use Selected Item", type="primary", key="list_use_btn"):
                            remove_from_inventory(selected_item['barcode'], use_quantity)
                            st.rerun()
            else:
                st.info("📭 No items available to use. Add some items first!")
    
    with tab4:
        st.header("Inventory Statistics & Insights")
        
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

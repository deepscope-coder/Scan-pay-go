import cv2
from pyzbar.pyzbar import decode
import psycopg2
from datetime import datetime
import csv
import os
import time
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import decimal

# Connect to PostgreSQL database
def connect_db(max_retries=3, delay=2):
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                dbname=os.getenv("DB_NAME", "retail"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", "621424"),
                host=os.getenv("DB_HOST", "localhost"),
                port=os.getenv("DB_PORT", "5432")
            )
            return conn
        except Exception as e:
            print(f"❌ Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(delay)
    print("❌ Could not connect to database after retries.")
    return None

# Scan barcode using camera
def scan_barcode_from_camera():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Error: Could not open camera.")
        return None

    print("🔄 Scanning... Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Error: Could not read frame.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        barcodes = decode(thresh)
        if barcodes:
            for barcode in barcodes:
                barcode_data = barcode.data.decode('utf-8')
                barcode_type = barcode.type
                print(f"✅ Found {barcode_type} barcode: {barcode_data}")
                cap.release()
                cv2.destroyAllWindows()
                return barcode_data

        cv2.imshow('Barcode Scanner', thresh)
        if cv2.waitKey(30) & 0xFF == ord('q'):
            print("🛑 User quit the scanner.")
            break

    cap.release()
    cv2.destroyAllWindows()
    print("❌ No barcode detected.")
    return None

# Fetch product info
def fetch_product_details(conn, barcode):
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, category, price, stock FROM products WHERE barcode = %s",
                (barcode,)
            )
            product = cursor.fetchone()
            if product:
                id, name, category, price, stock = product
                price = float(price) if isinstance(price, decimal.Decimal) else price
                print(f"📌 Product: {name}")
                print(f"🔖 Category: {category}")
                print(f"💰 Price: ₹{price:.2f}")
                print(f"📦 Stock: {stock} units")
                return id, name, price, stock if stock > 0 else None
            print("⚠️ Product not found!")
            return None
    except Exception as e:
        print(f"❌ Failed to fetch product details: {e}")
        return None

# Insert new customer
def insert_customer(conn, name, city_village, age, phone_number):
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO customer (name, city_village, age, phone_number) "
                "VALUES (%s, %s, %s, %s) RETURNING customer_id",
                (name, city_village, age, phone_number)
            )
            customer_id = cursor.fetchone()[0]
            conn.commit()
            print(f"📌 Customer {name} added with ID {customer_id}")
            return customer_id
    except Exception as e:
        print(f"❌ Failed to insert customer: {e}")
        conn.rollback()
        return None

# Record sale
def record_sale(conn, product_name, price, quantity, customer_id, purchase_time):
    try:
        with conn.cursor() as cursor:
            total_price = price * quantity
            cursor.execute(
                "INSERT INTO sales_history (product_name, price, quantity, total_price, customer_id, sale_time) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (product_name, price, quantity, total_price, customer_id, purchase_time)
            )
            conn.commit()
            print(f"📌 Sale recorded: {product_name} - ₹{total_price:.2f} ({quantity} pcs)")
    except Exception as e:
        print(f"❌ Failed to record sale: {e}")

# Update stock
def update_stock(conn, barcode, quantity):
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE products SET stock = stock - %s WHERE barcode = %s",
                (quantity, barcode)
            )
            conn.commit()
            print(f"✅ Stock updated: -{quantity} units")
    except Exception as e:
        print(f"❌ Failed to update stock: {e}")

# Quantity input
def get_valid_quantity(stock):
    while True:
        try:
            qty = int(input(f"🛒 Enter quantity (Max {stock}): "))
            if 0 < qty <= stock:
                return qty
            print(f"⚠️ Quantity must be between 1 and {stock}!")
        except ValueError:
            print("⚠️ Please enter a valid number!")

# Age input
def get_valid_age():
    while True:
        try:
            age = int(input("👤 Enter customer age: "))
            if age >= 0:
                return age
            print("⚠️ Age must be a positive number!")
        except ValueError:
            print("⚠️ Please enter a valid number!")

# Phone input
def get_valid_phone():
    while True:
        phone = input("📞 Enter customer phone number (optional, press Enter to skip): ").strip()
        if not phone:
            return None
        if phone.isdigit() and len(phone) <= 15:
            return phone
        print("⚠️ Phone number must be digits only and up to 15 characters!")

# Generate receipt (console + PDF)
def display_receipt(items, total_price, customer_info, purchase_time):
    GST_RATE = 0.05
    subtotal = float(total_price)
    gst_amount = subtotal * GST_RATE
    grand_total = subtotal + gst_amount

    customer_name, city_village, age, _ = customer_info

    print("\n" + "=" * 40)
    print("          🏪 PayGo Store Receipt          ")
    print("=" * 40)
    print(f"Date & Time: {purchase_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Customer: {customer_name}")
    print(f"City/Village: {city_village or 'N/A'}")
    print(f"Age: {age}")
    print("-" * 40)
    print(f"{'Item':<20} {'Price':>8} {'Qty':>5} {'Total':>8}")
    print("-" * 40)
    for item, price, qty, _ in items:
        total = price * qty
        print(f"{item[:19]:<20} {price:>8.2f} {qty:>5} {total:>8.2f}")
    print("-" * 40)
    print(f"{'Subtotal':<33} {subtotal:>8.2f}")
    print(f"{'GST (5%)':<33} {gst_amount:>8.2f}")
    print("=" * 40)
    print(f"{'GRAND TOTAL':<33} {grand_total:>8.2f} INR")
    print("=" * 40)

    filename = f"receipt_{purchase_time.strftime('%Y%m%d_%H%M%S')}.pdf"
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 50, "🏪 PayGo Store Receipt")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Date & Time: {purchase_time.strftime('%Y-%m-%d %H:%M:%S')}")
    c.drawString(50, height - 100, f"Customer: {customer_name}")
    c.drawString(50, height - 120, f"City/Village: {city_village or 'N/A'}")
    c.drawString(50, height - 140, f"Age: {age}")
    c.line(50, height - 150, width - 50, height - 150)

    y = height - 170
    for item, price, qty, _ in items:
        total = price * qty
        c.drawString(50, y, f"{item[:19]:<20} {price:>8.2f} {qty:>5} {total:>8.2f}")
        y -= 20

    c.drawString(50, y, f"{'Subtotal':<33} {subtotal:>8.2f}")
    y -= 20
    c.drawString(50, y, f"{'GST (5%)':<33} {gst_amount:>8.2f}")
    y -= 20
    c.drawString(50, y, f"{'GRAND TOTAL':<33} {grand_total:>8.2f}")
    y -= 30
    c.drawCentredString(width / 2, y, "Thank You for Shopping at PayGo!")
    c.save()
    print(f"📄 Receipt saved as {filename}")

# Export sales history
def export_sales_report(conn):
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM sales_history")
            sales = cursor.fetchall()

        filename = f"sales_report_{datetime.now().strftime('%Y-%m-%d')}.csv"
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Sale ID", "Product Name", "Price", "Quantity", "Total Price", "Customer ID", "Sale Time"])
            writer.writerows(sales)
            total_sales = sum(row[4] for row in sales)
            writer.writerow(["", "", "", "Total Sales", total_sales])

        print(f"📊 Sales report exported to {filename}")
    except Exception as e:
        print(f"❌ Failed to export sales report: {e}")

# Main system loop
def run_pos_system(conn):
    items = []
    total_price = 0
    purchase_time = datetime.now()

    customer_name = input("👤 Enter customer name (or press Enter for Guest): ").strip() or "Guest"
    city_village = input("🏙️ Enter customer city/village (optional): ").strip() or None
    age = get_valid_age()
    phone_number = get_valid_phone()

    customer_id = insert_customer(conn, customer_name, city_village, age, phone_number)
    if not customer_id:
        print("⚠️ Could not register customer.")
        return

    customer_info = (customer_name, city_village, age, phone_number)

    print("🔄 Bulk Scan Mode (type 'done' to finish):")
    while True:
        action = input("📸 Scan barcode? (yes/done): ").lower()
        if action == 'done':
            break
        elif action == 'yes':
            barcode = scan_barcode_from_camera()
            if barcode:
                product = fetch_product_details(conn, barcode)
                if product:
                    product_id, name, price, stock = product
                    if stock:
                        qty = get_valid_quantity(stock)
                        items.append((name, price, qty, barcode))
                        total_price += price * qty
                        print(f"✅ Added {name} x{qty}")
        else:
            print("⚠️ Enter 'yes' or 'done'.")

    if items:
        display_receipt(items, total_price, customer_info, purchase_time)
        if input("✅ Confirm sale? (yes/no): ").lower() == 'yes':
            for name, price, qty, barcode in items:
                record_sale(conn, name, price, qty, customer_id, purchase_time)
                update_stock(conn, barcode, qty)
            export_sales_report(conn)
            print("✅ Sale completed.")
        else:
            print("❌ Sale canceled.")
    else:
        print("⚠️ No items scanned.")

# Start
if __name__ == "__main__":
    conn = connect_db()
    if conn:
        try:
            run_pos_system(conn)
        finally:
            conn.close()
            print("🔒 Database connection closed.")
    else:
        print("❌ Cannot proceed without database connection.")

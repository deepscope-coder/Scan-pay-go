import os
import barcode
from barcode.writer import ImageWriter
import psycopg2
from dotenv import load_dotenv

load_dotenv()  # Load DB credentials from .env if available

# --- Connect to the database ---
def connect_db():
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
        print(f"❌ Database connection error: {e}")
        return None

# --- Generate and save barcodes ---
def generate_multiple_barcodes(data_list, output_prefix="barcode", output_folder="static/barcodes"):
    generated_files = []
    try:
        barcode_class = barcode.get_barcode_class('code128')
        os.makedirs(output_folder, exist_ok=True)

        conn = connect_db()

        for i, line in enumerate(data_list):
            line = line.strip()
            if not line:
                continue

            parts = [p.strip() for p in line.split(',')]
            if len(parts) != 5:
                print(f"❌ Skipping invalid input: '{line}'")
                continue

            barcode_data, name, category, price, stock = parts
            price = float(price)
            stock = int(stock)

            # Save barcode image
            filename = f"{output_prefix}_{i + 1}"
            full_path = os.path.join(output_folder, filename)
            saved_file = barcode_class(barcode_data, writer=ImageWriter()).save(full_path)
            relative_path = os.path.relpath(saved_file, start="static").replace("\\", "/")
            generated_files.append(relative_path)
            print(f"✅ Barcode saved: {saved_file}")

            # Update inventory
            if conn:
                update_product_in_inventory(conn, barcode_data, name, category, price, stock)

        if conn:
            conn.close()

        return generated_files

    except Exception as e:
        print(f"❌ Error generating barcodes: {e}")
        return []

# --- Update or insert product info in the inventory ---
def update_product_in_inventory(conn, barcode_data, name, category, price, stock):
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM products WHERE barcode = %s", (barcode_data,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute("""
                    UPDATE products
                    SET name = %s, category = %s, price = %s, stock = %s
                    WHERE barcode = %s
                """, (name, category, price, stock, barcode_data))
                print(f"✅ Updated existing product: {barcode_data}")
            else:
                cursor.execute("""
                    INSERT INTO products (barcode, name, category, price, stock)
                    VALUES (%s, %s, %s, %s, %s)
                """, (barcode_data, name, category, price, stock))
                print(f"✅ Inserted new product: {barcode_data}")
        conn.commit()
    except Exception as e:
        print(f"❌ Error updating inventory for barcode '{barcode_data}': {e}")

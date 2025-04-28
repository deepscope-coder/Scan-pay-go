from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session
from barcode_utils.barcode_generater import generate_multiple_barcodes
from barcode_utils.barcode_scanner import scan_barcode_from_camera, connect_db, fetch_product_details
from datetime import datetime
import os
import psycopg2

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'barcodes')
app.config['RECEIPT_FOLDER'] = os.path.join('static', 'receipts')  # Added directory for receipts
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit
app.secret_key = 'your_secret_key_here'  # Replace with a secure key

# Ensure barcode and receipt folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)

# Database connection setup
def connect_db():
    conn = psycopg2.connect(
        dbname="retail", user="postgres", password="621424", host="localhost"
    )
    return conn

# Fetch product details using barcode (returns a dictionary now)
def fetch_product_details(conn, barcode):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, category, price, stock 
        FROM products 
        WHERE barcode = %s
    """, (barcode,))
    row = cursor.fetchone()
    cursor.close()

    if row:
        return {
            'name': row[0],
            'category': row[1],
            'price': float(row[2]),
            'stock': row[3]
        }
    else:
        return None

# Save customer details
def save_customer(name, phone_number, city_village, age, email):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO customer (name, phone_number, city_village, age, email) 
        VALUES (%s, %s, %s, %s, %s)
        RETURNING customer_id;
    """, (name, phone_number, city_village, age, email))
    customer_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return customer_id

# Update product stock
def update_product_stock(barcode, quantity):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE products 
        SET stock = stock - %s 
        WHERE barcode = %s;
    """, (quantity, barcode))
    conn.commit()
    cursor.close()
    conn.close()

# Generate receipt (formatted with customer info, date, and time)
def generate_receipt(customer_id, basket_items, customer_details):
    # File path for the receipt in the receipts folder
    receipt_path = os.path.join(app.config['RECEIPT_FOLDER'], f"receipt_{customer_id}.txt")
    
    # Open the file in write mode with UTF-8 encoding
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(f"Customer ID: {customer_id}\n")
        f.write(f"Name: {customer_details.get('name', 'N/A')}\n")
        f.write(f"Email: {customer_details.get('email', 'N/A')}\n\n")
        f.write("Items Purchased:\n")
        
        total_price = 0
        for item in basket_items:
            f.write(f"Product: {item['name']} | Price: ₹{item['price']} | Quantity: {item['quantity']}\n")
            total_price += item['price'] * item['quantity']
        
        f.write(f"\nTotal Price: ₹{total_price}\n")
        f.write("\nThank you for shopping with us!\n")
    
    return receipt_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['GET', 'POST'])
def generate_barcodes():
    success_message = None
    error_message = None

    if request.method == 'POST':
        data = request.form.get('barcode_data')
        output_prefix = request.form.get('output_prefix', 'barcode')

        if data:
            data_list = [line.strip() for line in data.split('\n') if line.strip()]
            generated_files = generate_multiple_barcodes(
                data_list,
                output_prefix=output_prefix
            )
            if generated_files:
                success_message = f"✅ Barcodes generated successfully for {len(generated_files)} items."
            else:
                error_message = "❌ Failed to generate barcodes."

            return render_template('generate.html',
                                   files=generated_files,
                                   prefix=output_prefix,
                                   success_message=success_message,
                                   error_message=error_message)

        return redirect(url_for('generate_barcodes'))

    return render_template('generate.html')

@app.route('/scan', methods=['GET', 'POST'])
def scan_barcodes():
    conn = connect_db()
    result = None

    if 'basket' not in session:
        session['basket'] = []

    if request.method == 'POST':
        barcode_data = scan_barcode_from_camera()
        if barcode_data:
            product = fetch_product_details(conn, barcode_data)
            if product:
                item = {
                    'barcode': barcode_data,
                    'name': product['name'],
                    'category': product['category'],
                    'price': product['price'],
                    'stock': product['stock'],
                    'quantity': 1,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                session['basket'].append(item)
                session.modified = True
                result = item
            else:
                result = {'error': 'Product not found!'}
        else:
            result = {'error': 'Failed to scan the barcode.'}

    basket = session.get('basket', [])
    if conn:
        conn.close()
    return render_template('scan.html', result=result, basket=basket)

@app.route('/remove_product/<string:barcode>', methods=['POST'])
def remove_product(barcode):
    # Find the product in the basket and remove it
    basket = session.get('basket', [])
    basket = [item for item in basket if item['barcode'] != barcode]
    session['basket'] = basket
    session.modified = True
    return redirect(url_for('scan_barcodes'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        customer_name = request.form.get('name')
        phone_number = request.form.get('phone_number')
        city_village = request.form.get('city_village')
        age = request.form.get('age')
        customer_email = request.form.get('email')  # Get email from form

        # Save customer details and get the customer ID
        customer_details = {
            'name': customer_name,
            'phone_number': phone_number,
            'city_village': city_village,
            'email': customer_email  # Add email to customer details
        }
        customer_id = save_customer(customer_name, phone_number, city_village, age, customer_email)

        # Get the basket items from the session
        basket_items = session.get('basket', [])
        
        # Update product stock based on the basket items
        for item in basket_items:
            update_product_stock(item['barcode'], item['quantity'])

        # Generate the receipt
        receipt_file = generate_receipt(customer_id, basket_items, customer_details)
        
        # Clear the basket after checkout
        session.pop('basket', None)

        # Check if the user wants to download the receipt or proceed with payment
        if 'download_receipt' in request.form:
            return send_from_directory(app.config['RECEIPT_FOLDER'], f"receipt_{customer_id}.txt", as_attachment=True)
        else:
            # If it's "Proceed to Payment", you can implement the actual payment functionality here
            return redirect(url_for('payment', customer_id=customer_id))  # Redirect to payment page (optional)

    # Render the checkout page with basket details
    basket = session.get('basket', [])
    return render_template('checkout.html', basket=basket)

@app.route('/payment/<int:customer_id>', methods=['GET', 'POST'])
def payment(customer_id):
    # Implement your payment process here
    return render_template('payment.html', customer_id=customer_id)

@app.route('/barcodes/<filename>')  # Serve generated barcodes
def serve_barcode(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)

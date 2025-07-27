from flask import Flask, render_template, session, redirect, url_for, request, jsonify, send_file
import requests, random, sqlite3, ast, csv, io
from functools import wraps
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = 'a475d8d86a6db55e124d9f990884d147'

# API Keys
SPOONACULAR_API_KEY = '32c2a7d4a45b475b8d9587629fbd7449'
OPENCAGE_API_KEY = '4b1912a7bcce46ccbce4798de6f2363e'

# Admin login required decorator
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# ---------------- Admin Auth ----------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('view_orders'))
        else:
            return render_template('admin_login.html', error="Invalid credentials")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# ---------------- General Routes ----------------
@app.route('/')
def home():
    return redirect(url_for('menu'))

@app.route('/menu')
def menu():
    query = request.args.get('query', 'pizza')
    url = f"https://api.spoonacular.com/recipes/complexSearch?query={query}&number=10&apiKey={SPOONACULAR_API_KEY}"
    data = requests.get(url).json()
    menu = data.get('results', [])
    for item in menu:
        item['price'] = random.randint(100, 300)
    return render_template('menu.html', menu=menu, query=query)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    item = {
        'id': request.form['id'],
        'title': request.form['title'],
        'image': request.form['image'],
        'price': float(request.form['price'])
    }
    cart = session.get('cart', [])
    cart.append(item)
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart = session.get('cart', [])
    total = sum(item['price'] for item in cart)
    return render_template('cart.html', cart=cart, total=total)

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        cart = session.get('cart', [])
        total = sum(item['price'] for item in cart)

        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        address TEXT,
                        items TEXT,
                        total REAL,
                        status TEXT DEFAULT 'Preparing'
                    )''')
        c.execute("INSERT INTO orders (name, address, items, total, status) VALUES (?, ?, ?, ?, ?)",
                  (name, address, str(cart), total, 'Preparing'))
        conn.commit()
        conn.close()

        session['cart'] = []
        return render_template('thank_you.html', name=name, address=address)

    return render_template('checkout.html')

# ---------------- Admin Dashboard ----------------
@app.route('/orders')
@admin_required
def view_orders():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT rowid, name, address, items, total, status FROM orders")
    raw_orders = c.fetchall()
    conn.close()

    orders = []
    for row in raw_orders:
        order_id, name, address, items_str, total, status = row
        try:
            items = ast.literal_eval(items_str)
        except:
            items = []
    orders.append({
    'id': order_id,
    'name': name,
    'address': address,
    'items_list': items,   # ✅ FIXED name
    'total': total,
    'status': status
})

    return render_template('orders.html', orders=orders)

@app.route('/orders/<int:order_id>', methods=['GET', 'POST'])
@admin_required
def order_detail(order_id):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()

    if request.method == 'POST':
        new_status = request.form['status']
        c.execute("UPDATE orders SET status = ? WHERE rowid = ?", (new_status, order_id))
        conn.commit()

    c.execute("SELECT name, address, items, total, status FROM orders WHERE rowid = ?", (order_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return "Order not found", 404

    name, address, items_str, total, status = row
    try:
        items = ast.literal_eval(items_str)
    except:
        items = []

    statuses = ["Preparing", "Out for Delivery", "Delivered"]
    return render_template('order_detail.html', order_id=order_id, name=name, address=address, items=items, total=total, status=status, statuses=statuses)

# ---------------- PDF & CSV Export ----------------
@app.route('/export/csv')
@admin_required
def export_csv():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT name, address, items, total FROM orders")
    orders = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Address', 'Items', 'Total'])
    for order in orders:
        writer.writerow(order)

    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='orders.csv')

@app.route('/export/pdf')
@admin_required
def export_pdf():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT name, address, items, total FROM orders")
    orders = c.fetchall()
    conn.close()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica", 12)
    y = 800
    p.drawString(50, y, "Order List")
    y -= 30

    for idx, order in enumerate(orders, 1):
        name, address, items, total = order
        p.drawString(50, y, f"{idx}. Name: {name}, Address: {address}, Total: ₹{total}")
        y -= 20
        if y < 50:
            p.showPage()
            y = 800

    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='orders.pdf', mimetype='application/pdf')

# ---------------- My Recent Orders ----------------
@app.route('/my_orders')
def my_orders():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT rowid, name, address, items, total, status FROM orders ORDER BY rowid DESC LIMIT 5")
    raw_orders = c.fetchall()
    conn.close()

    recent_orders = []
    for row in raw_orders:
        order_id, name, address, items_str, total, status = row
        try:
            items = ast.literal_eval(items_str)
        except:
            items = []
        recent_orders.append({
            'id': order_id,
            'name': name,
            'address': address,
            'items_list': items,  # ✅ renamed to avoid conflict
            'total': total,
            'status': status
        })

    return render_template('my_orders.html', orders=recent_orders)

# ---------------- Geocoding for Map ----------------
@app.route('/geocode')
def geocode():
    address = request.args.get('address')
    if not address:
        return jsonify({'error': 'Address missing'}), 400

    url = f"https://api.opencagedata.com/geocode/v1/json?q={address}&key={OPENCAGE_API_KEY}"
    response = requests.get(url).json()

    if response['results']:
        coords = response['results'][0]['geometry']
        return jsonify({'lat': coords['lat'], 'lng': coords['lng']})
    else:
        return jsonify({'error': 'No location found'}), 404

# ---------------- Run ----------------
if __name__ == '__main__':
    app.run(debug=True)

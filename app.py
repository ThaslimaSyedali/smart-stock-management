from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3, os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DATABASE = 'stock.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def create_default_admin():
    with get_db_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", ('admin',)).fetchone()
        if not user:
            conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                         ('admin', generate_password_hash('admin123'), 'admin'))
            conn.commit()

def init_db():
    if not os.path.exists(DATABASE):
        with get_db_connection() as conn:
            with open('schema.sql', 'r') as f:
                conn.executescript(f.read())
    else:
        with get_db_connection() as conn:
            try:
                conn.execute('ALTER TABLE products ADD COLUMN expiry_date DATE')
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute('ALTER TABLE products ADD COLUMN tax REAL DEFAULT 18.0')
                conn.commit()
            except sqlite3.OperationalError:
                pass

def login_required(role=None):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in first.')
                return redirect(url_for('login'))
            user_role = session.get('role')
            if role and user_role != role:
                flash('Access denied: insufficient privileges.')
                if user_role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif user_role == 'counter':
                    return redirect(url_for('counter_billing'))
                else:
                    return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    if 'user_id' in session:
        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session['role'] == 'counter':
            return redirect(url_for('counter_billing'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        with get_db_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Logged in successfully!')
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'counter':
                return redirect(url_for('counter_billing'))
            else:
                flash('Unknown role. Contact administrator.')
                return redirect(url_for('login'))
        else:
            flash('Invalid username or password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('login'))

@app.route('/admin')
@login_required('admin')
def admin_dashboard():
    with get_db_connection() as conn:
        products = conn.execute('SELECT * FROM products').fetchall()
    low_stock = []
    expiring_soon = []
    now = datetime.now().date()
    soon = now + timedelta(days=30)
    for p in products:
        if p['quantity'] is not None and p['reorder_level'] is not None and p['quantity'] <= p['reorder_level']:
            low_stock.append(p)
        expiry_date = p['expiry_date']
        if expiry_date:
            try:
                expiry_obj = datetime.strptime(expiry_date, "%Y-%m-%d").date()
                if expiry_obj <= soon:
                    expiring_soon.append(p)
            except Exception:
                continue
    return render_template('admin_dashboard.html',
                           products=products,
                           low_stock=low_stock,
                           expiring_soon=expiring_soon,
                           username=session.get('username'))

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required('admin')
def add_product():
    if request.method == 'POST':
        name = request.form['name'].strip()
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])
        reorder_level = int(request.form.get('reorder_level', 5))
        expiry_date = request.form.get('expiry_date', None)
        with get_db_connection() as conn:
            product = conn.execute("SELECT * FROM products WHERE name = ?", (name,)).fetchone()
            if product:
                conn.execute('UPDATE products SET quantity = quantity + ?, price = ?, reorder_level = ?, expiry_date = ? WHERE name = ?',
                             (quantity, price, reorder_level, expiry_date, name))
            else:
                conn.execute('INSERT INTO products (name, quantity, price, reorder_level, expiry_date) VALUES (?, ?, ?, ?, ?)',
                             (name, quantity, price, reorder_level, expiry_date))
            conn.commit()
        flash('Product added/restocked successfully!')
        return redirect(url_for('admin_dashboard'))
    return render_template('add_product.html', username=session.get('username'))

@app.route('/admin/restock/<int:product_id>', methods=['GET', 'POST'])
@login_required('admin')
def restock_product(product_id):
    with get_db_connection() as conn:
        product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        if request.method == 'POST':
            add_qty = int(request.form['add_quantity'])
            new_qty = product['quantity'] + add_qty
            conn.execute('UPDATE products SET quantity = ? WHERE id = ?', (new_qty, product_id))
            conn.commit()
            flash('Product restocked successfully!')
            return redirect(url_for('admin_dashboard'))
    return render_template('restock_product.html', product=product, username=session.get('username'))

@app.route('/admin/sales')
@login_required('admin')
def view_sales():
    with get_db_connection() as conn:
        sales = conn.execute(
            'SELECT sales.id, products.name, sales.quantity, sales.date '
            'FROM sales JOIN products ON sales.product_id = products.id '
            'ORDER BY sales.date DESC'
        ).fetchall()
    return render_template('sales.html', sales=sales, username=session.get('username'))

@app.route('/admin/add_user', methods=['GET', 'POST'])
@login_required('admin')
def add_user():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role = request.form['role']
        if not username or not password or not role:
            flash('Please fill all fields!')
        else:
            with get_db_connection() as conn:
                try:
                    conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                                 (username, generate_password_hash(password), role))
                    conn.commit()
                    flash('User added successfully!')
                except sqlite3.IntegrityError:
                    flash('Username already exists!')
            return redirect(url_for('add_user'))
    return render_template('add_user.html', username=session.get('username'))

@app.route('/admin/users')
@login_required('admin')
def list_users():
    with get_db_connection() as conn:
        users = conn.execute('SELECT id, username, role FROM users').fetchall()
    return render_template('list_users.html', users=users, username=session.get('username'))

@app.route('/counter', methods=['GET', 'POST'])
@login_required('counter')
def counter_billing():
    with get_db_connection() as conn:
        products = conn.execute('SELECT * FROM products').fetchall()

    if request.method == 'POST':
        items = []
        total = 0
        tax_total = 0
        with get_db_connection() as conn:
            for product in products:
                qty_str = request.form.get(f'qty_{product["id"]}', '0')
                try:
                    qty = int(qty_str)
                except ValueError:
                    qty = 0
                if qty > 0:
                    if qty > product['quantity']:
                        flash(f"Not enough stock for {product['name']}")
                        continue
                    price = product["price"]
                    tax_rate = product["tax"] if product["tax"] is not None else 18.0
                    tax = price * qty * tax_rate / 100
                    line_total = price * qty + tax
                    total += price * qty
                    tax_total += tax
                    items.append({
                        "id": product["id"],
                        "name": product["name"],
                        "qty": qty,
                        "price": price,
                        "tax_rate": tax_rate,
                        "tax": tax,
                        "line_total": line_total,
                        "stock_left": product["quantity"] - qty
                    })
                    conn.execute('UPDATE products SET quantity = ? WHERE id = ?', (product['quantity'] - qty, product['id']))
                    conn.execute('INSERT INTO sales (product_id, quantity) VALUES (?, ?)', (product['id'], qty))
            conn.commit()
        grand_total = total + tax_total
        return render_template('receipt.html',
                               items=items,
                               total=total,
                               tax_total=tax_total,
                               grand_total=grand_total,
                               username=session.get('username'))
    return render_template('counter.html', products=products, username=session.get('username'))

    
if __name__ == '__main__':
    init_db()
    create_default_admin()
    app.run(debug=True)

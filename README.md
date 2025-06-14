# 💧 Water Refilling Station Management System

A standalone, easy-to-deploy Django-based web application designed to streamline daily operations of a water refilling station — from customer records to real-time inventory tracking, sales transactions, and automated reports.

---

## 🚀 Features

- ✅ **Customer Management**: Add, update, and store customer information
- 💵 **Sales Transactions**: Record sales with quantity, price per gallon, and payment status
- 📦 **Inventory Monitoring**: Track gallons in stock (in/out)
- 📊 **Reports**:
  - Daily and Monthly Sales Summary
  - Total Quantity Sold and Income Earned
- 🧾 **PDF Quotations** (for owner demos or business proposals)
- 🖥️ **User-friendly Web Interface** (responsive and ready to use)

---

## 🛠️ Built With

- Python 3.9+
- Django 4.2.x
- SQLite3 (default)
- Bootstrap 5 (for frontend templates)

---

## 📦 Installation Guide (Local / Demo)

```bash
# Clone this repository
git clone https://github.com/gemi-dot/water_refilling_station.git
cd water_refilling_station

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver

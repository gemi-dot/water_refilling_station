import os
import sys
import django
import webbrowser
import threading
import time
from django.core.management import execute_from_command_line

def setup_django():
    # Add project to Python path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # Set Django settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_refilling_station.settings')
    
    # Setup Django
    django.setup()

def open_browser():
    time.sleep(3)  # Wait for server to start
    webbrowser.open('http://127.0.0.1:8000')

def main():
    print("Starting Water Refilling Station...")
    setup_django()
    
    # Open browser in background
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    # Start Django server
    execute_from_command_line(['manage.py', 'runserver', '127.0.0.1:8000', '--noreload'])

if __name__ == '__main__':
    main()
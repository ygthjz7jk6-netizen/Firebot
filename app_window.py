import os
import sys
import threading
import time
import uvicorn
import webview

# Add local path to sys.path so we can import ui
base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_path)

from ui import app

port = 8899
url = f"http://localhost:{port}"

def start_server():
    """Starts the FastAPI server in a background thread."""
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

if __name__ == '__main__':
    # Start the web server in a daemon thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Create the native window
    window = webview.create_window('Firebot', url, width=1200, height=800, background_color='#0a0a14', text_select=True)
    
    # Start the webview GUI loop
    webview.start(debug=False)

    print("\n⚡ Ukončuji Firebot App...")
    os._exit(0)

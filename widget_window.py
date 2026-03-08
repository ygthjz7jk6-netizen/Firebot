import os
import sys
import webview

# Use the same port as the main app
port = int(os.environ.get("UI_PORT", "8899"))
url = f"http://localhost:{port}/widget"

if __name__ == '__main__':
    # Create the widget window: frameless, smaller, somewhat transparent
    # easy_drag=True allows moving the window by clicking anywhere (if configured in HTML)
    window = webview.create_window(
        'Firebot Widget', 
        url, 
        width=320, 
        height=450, 
        frameless=True, 
        easy_drag=True,
        background_color='#FFFBED',
        transparent=True,
        on_top=True # Keep it accessible
    )
    
    # Start the webview GUI loop
    webview.start(debug=False)

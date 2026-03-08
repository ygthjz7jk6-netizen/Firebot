import os
import sys
import threading
import webview
import rumps
import socket
import subprocess
import time

# Port and URL
port = int(os.environ.get("UI_PORT", "8899"))
url = f"http://localhost:{port}/menubar"

class FirebotMenubarApp(rumps.App):
    def __init__(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icon_with_bg.png")
        super(FirebotMenubarApp, self).__init__("Firebot", icon=icon_path, template=False)
        # Use a template icon if possible, or just text for now
        self.title = None 
        
        self.window = None
        self._is_visible = False
        self._server_running = False
        self._base_path = os.path.dirname(os.path.abspath(__file__))

        # Initial menu state
        self.menu = [
            rumps.MenuItem("Načítání...", callback=None),
            None, # Separator
            rumps.MenuItem("Ukončit", callback=rumps.quit_application)
        ]

        # Auto-launch main Firebot window on startup
        threading.Thread(target=self._auto_launch, daemon=True).start()

        # Start background threads
        threading.Thread(target=self.update_menu_periodically, daemon=True).start()

    def _auto_launch(self):
        """Auto-launch the main Firebot window on startup if not already running."""
        time.sleep(0.5)
        if not self.check_server():
            script_path = os.path.join(self._base_path, "app_window.py")
            subprocess.Popen([sys.executable, script_path], start_new_session=True)
            print("🚀 Auto-spouštím Firebot...")
        
        # Initialize webview in a separate thread because webview.start() is blocking
        # and rumps.run() is also blocking.
        # Actually, on macOS, webview must be on the main thread for some features.
        # This is the tricky part. Let's try to initialize the window ONLY when needed.

    def check_server(self):
        """Checks if the Firebot server is running on the specified port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0

    @rumps.clicked("Spustit Firebot")
    def launch_firebot(self, _):
        """Launches the main Firebot application."""
        if self._server_running:
            return
            
        script_path = os.path.join(self._base_path, "app_window.py")
        subprocess.Popen([sys.executable, script_path], start_new_session=True)
        print("🚀 Spouštím Firebot...")

    @rumps.clicked("Zobrazit Objednávky")
    def toggle_window(self, _):
        if not self._server_running:
            self.launch_firebot(_)
            return

        if self.window is None:
            # Create window on first demand if not already created
            # Note: create_window normally needs to be on main thread.
            # We'll use a hack or ensure it works here.
            self.create_window()
            # We need to start the webview loop. THIS IS THE 2ND BLOCKING CALL.
            # On Mac, we can try gui='cocoa' and non-blocking if possible.
            threading.Thread(target=webview.start, kwargs={'debug': False}, daemon=True).start()
            # Wait a bit for window to be created
            time.sleep(1)
        
        if self._is_visible:
            self.window.hide()
            self._is_visible = False
        else:
            self.window.show()
            self.window.restore()
            self._is_visible = True

    def create_window(self):
        self.window = webview.create_window(
            'Firebot Orders',
            url,
            width=320,
            height=450,
            frameless=True,
            easy_drag=True,
            on_top=True,
            hidden=True,
            transparent=True,
            background_color='#FFFBED'
        )

    def update_menu_periodically(self):
        """Periodic background task to check server status and update menu."""
        while True:
            new_status = self.check_server()
            if new_status != self._server_running:
                self._server_running = new_status
                self.update_menu_gui()
            time.sleep(5)

    def update_menu_gui(self):
        status_text = "Firebot: Běží" if self._server_running else "Firebot: Vypnutý"
        
        new_menu = []
        if self._server_running:
            new_menu.append(rumps.MenuItem('Zobrazit Objednávky', callback=self.toggle_window))
        else:
            new_menu.append(rumps.MenuItem('Spustit Firebot', callback=self.launch_firebot))
            
        new_menu.append(rumps.MenuItem(status_text))
        new_menu.append(None)
        new_menu.append(rumps.MenuItem('Ukončit', callback=rumps.quit_application))
        
        self.menu.clear()
        self.menu = new_menu

if __name__ == '__main__':
    # Initial status check
    app = FirebotMenubarApp()
    app.run()

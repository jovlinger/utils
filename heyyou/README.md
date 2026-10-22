Browser Notification Requirements
Safari (iOS and iPadOS):
• Regular browser tabs block the Notification API and suspend Server-Sent Events when backgrounded.
• Tap Share and select Add to Home Screen to run the site as a standalone Progressive Web App (PWA).
• Open the installed home-screen app once and grant permission via user gesture.
Safari (macOS):
• Works in a standard or pinned tab.
• Requires a user click gesture to trigger Notification.requestPermission().
Chrome and Firefox (Desktop and Android):
• Works in a standard open tab.
• Requires a user click gesture to trigger Notification.requestPermission().
• Background tabs may throttle Server-Sent Events, so keep the tab active or pinned.
server.py
python
#!/usr/bin/env python3
import http.server
import json
import threading
import time

clients = []
lock = threading.Lock()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            with open("index.html", "rb") as f:
                self.wfile.write(f.read())
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = []
            with lock:
                clients.append(q)
            try:
                while True:
                    if q:
                        msg = q.pop(0)
                        self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                        self.wfile.flush()
                    else:
                        time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    if q in clients:
                        clients.remove(q)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/notify":
            clen = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(clen)
            data = json.loads(body.decode("utf-8") or "{}")
            with lock:
                for q in clients:
                    q.append(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8080), Handler)
    print("Listening on 0.0.0.0:8080")
    server.serve_forever()
Use code with caution.
index.html
html
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Mac Alerts</title>
</head>
<body style="font-family: monospace; background: #111; color: #eee; padding: 20px;">
    <h3>Mac Alert Stream</h3>
    <button onclick="Notification.requestPermission()" style="padding: 10px; background: #333; color: #fff; border: 1px solid #555;">Enable Screen Notifications</button>
    <pre id="log" style="margin-top: 20px; white-space: pre-wrap;"></pre>
    <script>
        const evtSource = new EventSource('/events');
        evtSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            const timestamp = new Date().toLocaleTimeString();
            document.getElementById('log').textContent += `[${timestamp}] ${data.title}: ${data.message}\n`;
            if (Notification.permission === 'granted') {
                new Notification(data.title, { body: data.message });
            }
        };
    </script>
</body>
</html>
Use code with caution.
Execution and Trigger
Start the server on Linux:
bash
python3 server.py &
Use code with caution.
Open the page on the client device:
Navigate to http://LINUX_IP:8080 and click the enable button.
Trigger from macOS via Terminal or AppleScript:
bash
osascript -e 'do shell script "curl -X POST -H \"Content-Type: application/json\" -d \"{\\\"title\\\":\\\"Build\\\", \\\"message\\\":\\\"Done\\\"}\" http://LINUX_IP:8080/notify"'
Use code with caution.
If you want to pin this down for permanent use, let me know:
• Do you want the systemd service unit for Linux?
• Do you want a zsh/bash shell wrapper function for macOS?


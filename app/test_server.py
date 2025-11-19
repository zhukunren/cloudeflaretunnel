#!/usr/bin/env python3
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys

class MyHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"""
<!DOCTYPE html>
<html>
<head><title>Test Server</title></head>
<body>
<h1>Cloudflare Tunnel Test</h1>
<p>Server is working! Port: 8501</p>
<p>Time: <script>document.write(new Date());</script></p>
</body>
</html>
""")

print("Starting test server on port 8501...")
httpd = HTTPServer(('0.0.0.0', 8501), MyHandler)
print("Server running at http://localhost:8501")
httpd.serve_forever()

"""Entry point: python api/start.py [--port 8080]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api.server import run_server

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8080
    run_server(port=port)

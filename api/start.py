"""Entry point: python api/start.py [--port 8080] [--host 0.0.0.0] [--db data/registry.db]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api.server import run_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Registry API server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: $REGISTRY_DB or data/registry.db)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host, db_path=args.db)

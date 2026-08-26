"""
Quick helper: calls /api/annotate-carpark and saves the returned image to
disk so you can actually look at it, instead of reading raw base64 text.

Usage:
    python view_annotated.py CBD_001
"""

import base64
import json
import sys
import urllib.request

carpark_id = sys.argv[1] if len(sys.argv) > 1 else "CBD_001"
url = f"http://127.0.0.1:8000/api/annotate-carpark?carpark_id={carpark_id}"

with urllib.request.urlopen(url) as resp:
    data = json.load(resp)

if data["status"] != "success":
    print("Error:", data["msg"])
    sys.exit(1)

out_path = f"annotated_{carpark_id}.png"
with open(out_path, "wb") as f:
    f.write(base64.b64decode(data["image_base64"]))

print(f"Saved {out_path}, open it to see the bounding boxes.")

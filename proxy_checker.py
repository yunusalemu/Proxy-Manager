import json
import socks
import socket
import requests
import concurrent.futures
import threading
from pathlib import Path

lock = threading.Lock()

# ---------- Helpers ----------
def clean_proxy_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if "|" in line:
        line = line.split("|")[0]
    return line

def parse_proxy_line(line):
    line = clean_proxy_line(line)
    parts = line.split(":")
    if len(parts) == 2:
        return parts[0], int(parts[1]), None, None
    elif len(parts) == 4:
        return parts[0], int(parts[1]), parts[2], parts[3]
    return None, None, None, None

def classify_connection(isp_name: str):
    isp_lower = isp_name.lower()
    if any(x in isp_lower for x in ["comcast", "spectrum", "verizon", "cable", "dsl", "fiber", "fios"]):
        return "Residential"
    if any(x in isp_lower for x in ["mobile", "cellular", "wireless", "lte", "4g", "5g"]):
        return "Cellular"
    if any(x in isp_lower for x in ["hosting", "datacenter", "server", "cloud", "colo"]):
        return "Business"
    return "Residential"

def test_proxy(proxy_line):
    proxy_line = clean_proxy_line(proxy_line)
    host, port, user, password = parse_proxy_line(proxy_line)
    if not host or not port:
        return None

    try:
        # Simple socket test
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, host, port, username=user, password=password)
        s.settimeout(3)
        s.connect(("www.google.com", 80))
        s.send(b"GET / HTTP/1.1\r\nHost: google.com\r\n\r\n")
        data = s.recv(1024)
        s.close()
        if b"HTTP" not in data:
            return None

        # Geo lookup
        proxies_dict = {
            "http": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
            "https": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
        }
        r = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=10)
        geo = r.json()
        if geo.get("status") != "success":
            return None

        return {
            "proxy": proxy_line,
            "ip": geo.get("query", "?"),
            "country": geo.get("country", "?"),
            "region": geo.get("regionName", "?"),
            "city": geo.get("city", "?"),
            "zip": geo.get("zip", "?"),
            "isp": geo.get("isp", "?"),
            "blacklist": "No",
            "use_type": classify_connection(geo.get("isp", "")),
        }

    except Exception:
        return None


# ---------- Main ----------
def main():
    active_path = Path("Active_Proxies.json")
    new_path = Path("New_Proxies.txt")

    # Load current active JSON
    if active_path.exists():
        with open(active_path, "r", encoding="utf-8") as f:
            try:
                active_proxies = json.load(f)
            except:
                active_proxies = []
    else:
        active_proxies = []

    # Test all currently active proxies → keep only good ones
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_proxy, p["proxy"]) for p in active_proxies]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    active_proxies = [r for r in results if r]

    # Read new proxies from txt
    if new_path.exists():
        with open(new_path, "r", encoding="utf-8", errors="ignore") as f:
            new_proxies = [line.strip() for line in f if line.strip()]
    else:
        new_proxies = []

    # Test new proxies
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_proxy, p) for p in new_proxies]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    new_active = [r for r in results if r]

    # Merge new on top + remove duplicates
    all_proxies = new_active + active_proxies
    seen = set()
    final_list = []
    for p in all_proxies:
        if p["proxy"] not in seen:
            final_list.append(p)
            seen.add(p["proxy"])

    # Save updated JSON
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(final_list, f, indent=2, ensure_ascii=False)

    print(f"✅ Updated Active_Proxies.json with {len(final_list)} working proxies")


if __name__ == "__main__":
    main()

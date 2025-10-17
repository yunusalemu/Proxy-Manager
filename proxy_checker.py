import socks
import socket
import concurrent.futures
import requests
import threading
import os
import json
from datetime import datetime

lock = threading.Lock()  # ensures file writes don't clash


def clean_proxy_line(line):
    """Strip off everything after host:port:user:pass (or host:port)."""
    line = line.strip()
    if not line:
        return ""

    if "|" in line:  # remove metadata if present
        line = line.split("|")[0]

    return line


def parse_proxy_line(line):
    line = clean_proxy_line(line)
    if not line:
        return None, None, None, None

    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return host, int(port), None, None
    elif len(parts) == 4:
        host, port, user, password = parts
        return host, int(port), user, password
    else:
        return None, None, None, None


def classify_connection(isp_name):
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
        return False, proxy_line, None

    # Try SOCKS5, then SOCKS4
    for proxy_type in [socks.SOCKS5, socks.SOCKS4]:
        try:
            s = socks.socksocket()
            s.set_proxy(proxy_type, host, port, username=user, password=password)
            s.settimeout(5)
            s.connect(("www.sefan.ru", 80))
            s.send(b"GET / HTTP/1.1\r\nHost: sefan.ru\r\n\r\n")
            data = s.recv(1024)
            s.close()

            if b"HTTP" not in data:
                continue

            proxies_dict = {
                "http": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
                "https": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
            }

            geo = {}
            try:
                r = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=10)
                geo = r.json() if r.status_code == 200 else {}
            except Exception:
                pass

            ip = geo.get("query", "Unknown")
            country = geo.get("country", "Unknown")
            region = geo.get("regionName", "Unknown")
            city = geo.get("city", "Unknown")
            zip_code = geo.get("zip", "Unknown")
            isp = geo.get("isp", "Unknown")
            connection_type = classify_connection(isp if isp != "Unknown" else "")

            formatted = (
                f"{proxy_line}|"
                f"{ip}|{country}|{region}|{city}|{zip_code}|{isp}|"
                f"Black List: No|Use Type: {connection_type}"
            )

            return True, proxy_line, formatted

        except Exception:
            continue

    return False, proxy_line, None


# ==================== GOOGLE SHEET UPLOAD (Apps Script) ====================

def upload_to_google_sheet_via_webapp(working_data):
    """Send the proxy info to Google Sheet via Apps Script WebApp endpoint."""
    WEB_APP_URL = "https://script.google.com/macros/s/AKfycbzZ08wO082Ybhk5WIL_Kwo9qo_u-3rKXnC8jLSiuDABhgdueoduu0t00MPT51noBtgY/exec"  # <-- Replace with your deployed Web App URL

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = []
    for item in working_data:
        parts = item.split("|")
        if len(parts) >= 8:
            proxy_full = parts[0].strip()
            country = parts[2]
            region = parts[3]
            city = parts[4]
            isp = parts[6]
            proxy_type = parts[-1].split(":")[-1].strip()

            rows.append({
                "ipdata": proxy_full,
                "country": country,
                "region": region,
                "city": city,
                "isp": isp,
                "proxy_type": proxy_type,
                "last_updated": timestamp
            })

    if not rows:
        print("⚠️ No valid proxy data to upload.")
        return

    try:
        response = requests.post(WEB_APP_URL, json=rows, timeout=30)
        if response.ok:
            print(f"📤 Uploaded {len(rows)} proxies to Google Sheet successfully at {timestamp}.")
        else:
            print(f"❌ Failed to upload data: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Error uploading to Google Sheet: {e}")


# ===========================================================================


def main():
    if not os.path.exists("New_Proxies.txt"):
        print("⚠️ No New_Proxies.txt found.")
        return

    with open("New_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
        raw_proxies = [clean_proxy_line(p) for p in f if p.strip()]

    seen = set()
    unique_proxies = []
    for p in raw_proxies:
        if p and p not in seen:
            seen.add(p)
            unique_proxies.append(p)

    with open("New_Proxies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(unique_proxies) + "\n")

    print(f"🧽 Cleaned duplicates — {len(unique_proxies)} unique proxies found.\n")
    print("🔍 Checking new proxies...")

    cpu_threads = os.cpu_count() or 4
    max_workers = min(50, cpu_threads * 5)

    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(test_proxy, p) for p in unique_proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy, formatted = future.result()
            if ok:
                working.append(formatted)
                print(f"✅ {formatted}")
            else:
                print(f"❌ {proxy.strip()} Inactive")

    print("\n📦 Processing completed. Preparing to write and upload results...\n")

    if working:
        with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(working) + "\n")
        print(f"💾 Replaced Active_Proxies.txt with {len(working)} working proxies.")
        upload_to_google_sheet_via_webapp(working)
    else:
        open("Active_Proxies.txt", "w").close()
        print("⚠️ No working proxies. Active_Proxies.txt has been cleared.")


if __name__ == "__main__":
    main()

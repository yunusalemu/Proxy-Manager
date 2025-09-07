import socks
import socket
import concurrent.futures
import requests
import threading
import os

lock = threading.Lock()  # ensures file writes don't clash


def clean_proxy_line(line):
    """Strip off everything after host:port:user:pass (or host:port)."""
    line = line.strip()
    if not line:
        return ""

    # If the line already has extra "|" info (from output file), take only the proxy part
    if "|" in line:
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

    try:
        # Test proxy connection
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, host, port, username=user, password=password)
        s.settimeout(3)
        s.connect(("www.google.com", 80))
        s.send(b"GET / HTTP/1.1\r\nHost: google.com\r\n\r\n")
        data = s.recv(1024)
        s.close()
        if b"HTTP" not in data:
            return False, proxy_line, None

        # If working → fetch real geo details
        proxies_dict = {
            "http": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
            "https": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
        }
        r = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=10)
        geo = r.json()
        if geo.get("status") != "success":
            return False, proxy_line, None

        # Format result with Blacklist + Use Type
        connection_type = classify_connection(geo.get("isp", ""))
        formatted = (
            f"{proxy_line}|"
            f"{geo.get('query', '?')}|"
            f"{geo.get('country', '?')}|"
            f"{geo.get('regionName', '?')}|"
            f"{geo.get('city', '?')}|"
            f"{geo.get('zip', '?')}|"
            f"{geo.get('isp', '?')}|"
            f"Black List: No|Use Type: {connection_type}"
        )

        return True, proxy_line, formatted

    except Exception:
        return False, proxy_line, None


def main():
    if not os.path.exists("New_Proxies.txt"):
        print("⚠️ No New_Proxies.txt found.")
        return

    with open("New_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
        proxies = [p.strip() for p in f if p.strip()]

    print("🔍 Checking new proxies...")

    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(test_proxy, p) for p in proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy, formatted = future.result()
            if ok:
                working.append(formatted)
                print(f"✅ {formatted}")
            else:
                print(f"❌ {proxy.strip()} Inactive")

    if not working:
        print("\nNo new working proxies found.")
        return

    # Load existing active proxies
    if os.path.exists("Active_Proxies.txt"):
        with open("Active_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
            active = [line.strip() for line in f if line.strip()]
    else:
        active = []

    # Merge: new first, then old, no duplicates
    combined = list(dict.fromkeys(working + active))

    with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(combined) + "\n")

    print(f"\n💾 Added {len(working)} new proxies to Active_Proxies.txt.")


if __name__ == "__main__":
    main()

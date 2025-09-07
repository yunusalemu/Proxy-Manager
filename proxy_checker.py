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

    # Remove unwanted characters that sometimes appear from JSON/CSV exports
    for bad in ['"', "'", ",", "[", "]", "{", "}"]:
        line = line.replace(bad, "")

    # If line already has extra "|" info (geo data, blacklist, etc), take only the proxy part
    if "|" in line:
        line = line.split("|")[0]

    # If too many colons → limit to host:port or host:port:user:pass
    parts = line.split(":")
    if len(parts) > 4:
        line = ":".join(parts[:4])

    return line.strip()




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

        # If working → fetch geo details
        proxies_dict = {
            "http": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
            "https": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
        }
        r = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=10)
        geo = r.json()
        if geo.get("status") != "success":
            return False, proxy_line, None

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
    # Read existing active proxies
    if os.path.exists("Active_Proxies.txt"):
        with open("Active_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
            active_proxies = [clean_proxy_line(p) for p in f if clean_proxy_line(p)]
    else:
        active_proxies = []

    # Recheck all active proxies
    print("♻️ Rechecking Active_Proxies.txt...")
    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_proxy, p) for p in active_proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy, formatted = future.result()
            if ok:
                working.append(formatted)
                print(f"✅ {formatted}")
            else:
                print(f"❌ {proxy.strip()} removed")

    # Test new proxies
    if os.path.exists("New_Proxies.txt"):
        with open("New_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
            new_proxies = [clean_proxy_line(p) for p in f if clean_proxy_line(p)]
    else:
        new_proxies = []

    print("\n➕ Checking New_Proxies.txt...")
    new_working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_proxy, p) for p in new_proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy, formatted = future.result()
            if ok:
                new_working.append(formatted)
                print(f"✅ NEW {formatted}")
            else:
                print(f"❌ NEW {proxy.strip()} ignored")

    # Merge: new proxies first, then existing ones, no duplicates
    combined = list(dict.fromkeys(new_working + working))

    # Save back to Active_Proxies.txt
    with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(combined) + "\n")

    # Clear New_Proxies.txt (processed)
    open("New_Proxies.txt", "w").close()

    print("\n💾 Active_Proxies.txt updated.")


if __name__ == "__main__":
    main()

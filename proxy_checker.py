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
            # Test connection
            s = socks.socksocket()
            s.set_proxy(proxy_type, host, port, username=user, password=password)
            s.settimeout(15)
            s.connect(("www.sefan.ru", 80))
            s.send(b"GET / HTTP/1.1\r\nHost: google.com\r\n\r\n")
            data = s.recv(1024)
            s.close()

            if b"HTTP" not in data:
                continue  # try next proxy type

            # If we got here → proxy works
            proxies_dict = {
                "http": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
                "https": f"socks5h://{user+':'+password+'@' if user else ''}{host}:{port}",
            }

            geo = {}
            try:
                r = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=15)
                geo = r.json() if r.status_code == 200 else {}
            except Exception:
                pass  # don’t reject proxy if geo fails

            # Use geo data if available, else fallback to Unknown
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
            continue  # try next proxy type

    return False, proxy_line, None  # failed both SOCKS5 and SOCKS4


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

    # Always overwrite Active_Proxies.txt
    if working:
        with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(working) + "\n")
        print(f"\n💾 Replaced Active_Proxies.txt with {len(working)} working proxies.")
    else:
        open("Active_Proxies.txt", "w").close()
        print("\n⚠️ No working proxies. Active_Proxies.txt has been cleared.")


if __name__ == "__main__":
    main()

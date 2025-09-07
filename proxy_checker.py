import socks
import socket
import concurrent.futures
import requests
import threading
import os

lock = threading.Lock()


def clean_proxy_line(line):
    """Keep only host:port or host:port:user:pass (strip anything after |)."""
    line = line.strip()
    if not line:
        return ""

    if "|" in line:  # remove extra metadata
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


def test_proxy(proxy_line):
    proxy_line = clean_proxy_line(proxy_line)
    host, port, user, password = parse_proxy_line(proxy_line)
    if not host or not port:
        return False, proxy_line

    try:
        # Basic socket test
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, host, port, username=user, password=password)
        s.settimeout(3)
        s.connect(("www.google.com", 80))
        s.send(b"GET / HTTP/1.1\r\nHost: google.com\r\n\r\n")
        data = s.recv(1024)
        s.close()
        if b"HTTP" not in data:
            return False, proxy_line

        return True, proxy_line

    except Exception:
        return False, proxy_line


def main():
    # Load new proxies
    if not os.path.exists("New_Proxies.txt"):
        print("⚠️ No New_Proxies.txt found.")
        return

    with open("New_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
        new_proxies = [p.strip() for p in f if p.strip()]

    print(f"🔍 Checking {len(new_proxies)} new proxies...")

    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_proxy, p) for p in new_proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy = future.result()
            if ok:
                working.append(proxy)
                print(f"✅ {proxy}")
            else:
                print(f"❌ {proxy}")

    if not working:
        print("\nNo new working proxies found.")
        return

    # Load existing active proxies
    if os.path.exists("Active_Proxies.txt"):
        with open("Active_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
            active = [clean_proxy_line(p) for p in f if p.strip()]
    else:
        active = []

    # Merge: new first, then old, no duplicates
    combined = list(dict.fromkeys(working + active))

    with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(combined) + "\n")

    # Clear new proxies file (processed)
    open("New_Proxies.txt", "w").close()

    print(f"\n💾 Added {len(working)} proxies to Active_Proxies.txt.")


if __name__ == "__main__":
    main()

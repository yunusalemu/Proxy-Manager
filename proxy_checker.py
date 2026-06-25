import socks
import concurrent.futures
import requests
import threading
import os
import base64
from datetime import datetime

lock = threading.Lock()

# ===================== ENCRYPTION =====================

ENCRYPT_KEY         = "socksproxysupport"  # ✅ Must match Unity ProxyLookUp key exactly
ENCRYPT_CREDENTIALS = False                 # 👈 Toggle — True = encrypted, False = plaintext

def xor_encrypt(text):
    if not text:
        return ""
    result = []
    for i, c in enumerate(text):
        result.append(chr(ord(c) ^ ord(ENCRYPT_KEY[i % len(ENCRYPT_KEY)])))
    return base64.b64encode("".join(result).encode("latin-1")).decode("utf-8")

def xor_decrypt(encoded):
    if not encoded:
        return ""
    if encoded.startswith("ENC:"):
        encoded = encoded[4:]
    try:
        decoded = base64.b64decode(encoded.encode("utf-8")).decode("latin-1")
        result  = []
        for i, c in enumerate(decoded):
            result.append(chr(ord(c) ^ ord(ENCRYPT_KEY[i % len(ENCRYPT_KEY)])))
        return "".join(result)
    except Exception:
        return encoded

def maybe_encrypt(text):
    if not text:
        return ""
    if ENCRYPT_CREDENTIALS:
        return "ENC:" + xor_encrypt(text)
    return text

# ======================================================


def clean_proxy_line(line):
    line = line.strip()
    if not line:
        return ""
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

    for proxy_type in [socks.SOCKS5, socks.SOCKS4]:
        try:
            s = socks.socksocket()
            s.set_proxy(proxy_type, host, port, username=user, password=password)
            s.settimeout(3)
            s.connect(("www.sefan.ru", 80))
            s.send(b"GET / HTTP/1.1\r\nHost: sefan.ru\r\n\r\n")
            data = s.recv(1024)
            s.close()

            if b"HTTP" not in data:
                continue

            proxies_dict = {
                "http":  f"socks5h://{user + ':' + password + '@' if user else ''}{host}:{port}",
                "https": f"socks5h://{user + ':' + password + '@' if user else ''}{host}:{port}",
            }

            geo = {}
            try:
                r   = requests.get("http://ip-api.com/json", proxies=proxies_dict, timeout=10)
                geo = r.json() if r.status_code == 200 else {}
            except Exception:
                pass

            country         = geo.get("country",    "Unknown")
            region          = geo.get("regionName", "Unknown")
            city            = geo.get("city",        "Unknown")
            zip_code        = geo.get("zip",         "Unknown")
            isp             = geo.get("isp",         "Unknown")
            connection_type = classify_connection(isp if isp != "Unknown" else "")

            # Build ipdata string — same format as before but credentials may be encrypted
            if user and password:
                enc_user = maybe_encrypt(user)
                enc_pass = maybe_encrypt(password)

                # Verify encryption round-trips correctly when enabled
                if ENCRYPT_CREDENTIALS:
                    if xor_decrypt(enc_user) != user or xor_decrypt(enc_pass) != password:
                        print(f"⚠️ Encryption verification failed for: {host}:{port}")
                        return False, proxy_line, None

                # Format: host:port:ENC:xxxxx:ENC:xxxxx (encrypted)
                #      or host:port:user:pass            (plaintext)
                ip_data_clean = f"{host}:{port}:{enc_user}:{enc_pass}"
            else:
                ip_data_clean = f"{host}:{port}"

            mode = "🔐 Encrypted" if ENCRYPT_CREDENTIALS else "🔓 Plaintext"
            print(f"✅ {host}:{port} | {country} / {region} | {isp} | {mode}")

            result = {
                "ip_data_clean": ip_data_clean,
                "country":       country,
                "region":        region,
                "city":          city,
                "zip_code":      zip_code,
                "isp":           isp,
                "proxy_type":    connection_type,
            }

            return True, proxy_line, result

        except Exception:
            continue

    return False, proxy_line, None


def upload_to_google_sheet(working_results):
    WEB_APP_URL = "YOUR_WEB_APP_URL_HERE"  # 👈 Replace with your deployed Web App URL
    timestamp   = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = []
    for r in working_results:
        rows.append({
            "ipdata":       r["ip_data_clean"],  # same column as before — sheet unchanged
            "country":      r["country"],
            "region":       r["region"],
            "city":         r["city"],
            "isp":          r["isp"],
            "proxy_type":   r["proxy_type"],
            "last_updated": timestamp
        })

    if not rows:
        print("⚠️ No valid proxy data to upload.")
        return

    try:
        response = requests.post(WEB_APP_URL, json=rows, timeout=30)
        if response.ok:
            mode = "encrypted" if ENCRYPT_CREDENTIALS else "plaintext"
            print(f"📤 Uploaded {len(rows)} proxies ({mode}) at {timestamp}.")
        else:
            print(f"❌ Upload failed: {response.status_code} {response.text}")
    except Exception as ex:
        print(f"⚠️ Upload error: {ex}")


def main():
    if not os.path.exists("New_Proxies.txt"):
        print("⚠️ No New_Proxies.txt found.")
        return

    mode = "🔐 ENCRYPTION ENABLED" if ENCRYPT_CREDENTIALS else "🔓 ENCRYPTION DISABLED (plaintext)"
    print(f"\n{'='*55}")
    print(f"  Key:             {ENCRYPT_KEY}")
    print(f"  Credential Mode: {mode}")
    print(f"{'='*55}\n")

    with open("New_Proxies.txt", "r", encoding="utf-8", errors="ignore") as f:
        raw_proxies = [clean_proxy_line(p) for p in f if p.strip()]

    seen, unique_proxies = set(), []
    for p in raw_proxies:
        if p and p not in seen:
            seen.add(p)
            unique_proxies.append(p)

    with open("New_Proxies.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(unique_proxies) + "\n")

    print(f"🧽 Cleaned duplicates — {len(unique_proxies)} unique proxies found.\n")
    print("🔍 Testing proxies...\n")

    cpu_threads = os.cpu_count() or 4
    max_workers = min(50, cpu_threads * 5)

    working_results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(test_proxy, p) for p in unique_proxies]
        for future in concurrent.futures.as_completed(futures):
            ok, proxy, result = future.result()
            if ok and result:
                working_results.append(result)
            else:
                print(f"❌ Dead: {proxy.strip()}")

    print(f"\n📦 Done. {len(working_results)} working proxies.\n")

    if working_results:
        with open("Active_Proxies.txt", "w", encoding="utf-8") as f:
            for r in working_results:
                f.write(
                    f"{r['ip_data_clean']}|"
                    f"{r['country']}|{r['region']}|{r['city']}|"
                    f"{r['isp']}|{r['proxy_type']}\n"
                )
        print(f"💾 Active_Proxies.txt written ({len(working_results)} proxies).")
        upload_to_google_sheet(working_results)
    else:
        open("Active_Proxies.txt", "w").close()
        print("⚠️ No working proxies. Active_Proxies.txt cleared.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
canlitv.you embed sayfalarından m3u8 URL'sini bulur, o URL'nin
GERÇEK m3u8 içeriğini indirir ve playlist/<slug>.m3u8 olarak kaydeder.
"""

import json
import os
import re
import sys
import time
import requests

# ---------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.path.join(BASE_DIR, "channels.json")
PLAYLIST_DIR = os.path.join(BASE_DIR, "playlist")

EMBED_DOMAIN = "https://www.canlitv.you"

# Embed isteği için tarayıcı başlıkları
EMBED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.canlitv.you/",
    "Origin": "https://www.canlitv.you",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}

# m3u8 içeriğini çekerken kullanılacak başlıklar
# (embed başlıklarıyla aynı — canlitv.you referer'ı geçerli)
STREAM_HEADERS = dict(EMBED_HEADERS)
STREAM_HEADERS["Accept"] = "*/*"

TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 3


# ---------------------------------------------------------------
# M3U8 URL AYIKLAMA (embed HTML'inden)
# ---------------------------------------------------------------
def extract_m3u8_url(html: str):
    """Embed HTML'inden m3u8 URL'sini çıkarır."""
    if not html:
        return None

    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    patterns = [
        r"""file\s*:\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""file\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""data-src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""data-lazy-src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""player\.(?:src|source)\s*\(\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""(?:hls|video)\.(?:loadSource|src)\s*\(\s*["']([^"']*\.m3u8[^"']*)["']""",
        r"""['"]source['"]\s*:\s*['"]([^'"]*\.m3u8[^'"]*)['"]""",
        r"""['"]url['"]\s*:\s*['"]([^'"]*\.m3u8[^'"]*)['"]""",
        r"""(https?://[^\s"'<>\\]+\.m3u8[^\s"'<>\\]*)""",
    ]

    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            url = m.group(1).strip()
            url = re.sub(r'[,\s"\'<>]+$', "", url)
            if len(url) > 20:
                return url
    return None


# ---------------------------------------------------------------
# M3U8 İÇERİĞİNİ DOĞRULA
# ---------------------------------------------------------------
def looks_like_m3u8(text: str) -> bool:
    """Dönen metin gerçek bir m3u8 içeriği mi?"""
    if not text:
        return False
    # İlk anlamlı satır #EXTM3U olmalı
    head = text.lstrip()[:64]
    return head.startswith("#EXTM3U")


# ---------------------------------------------------------------
# TEK KANAL: embed -> m3u8 URL -> gerçek m3u8 içeriği
# ---------------------------------------------------------------
def fetch_channel_m3u8_content(channel_id: str):
    """
    Returns:
        (m3u8_url, m3u8_content) -> başarılıysa
        (m3u8_url, None)         -> m3u8 URL bulundu ama içeriği alınamadı
        (None, None)             -> embed'den URL bile alınamadı
    """
    # 0) Oturum ısıtma
    try:
        onay_url = (
            f"https://canlitv.you/online/online.php"
            f"?sayfa={channel_id}&tur=1&ref=0&onay=1"
        )
        requests.get(onay_url, headers=EMBED_HEADERS, timeout=TIMEOUT)
        time.sleep(0.5)
    except Exception:
        pass

    embed_url = f"{EMBED_DOMAIN}/embed/?id={channel_id}&autoplay=1&muted=1"

    # 1) Embed sayfasını çek, m3u8 URL'sini al
    m3u8_url = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                embed_url, headers=EMBED_HEADERS,
                timeout=TIMEOUT, allow_redirects=True
            )
            resp.raise_for_status()
            m3u8_url = extract_m3u8_url(resp.text)
            if m3u8_url:
                print(f"  🔗 m3u8 URL bulundu: {m3u8_url[:100]}")
                break
            print(f"  [{channel_id}] Deneme {attempt}: HTML alındı ama m3u8 URL yok.")
        except Exception as e:
            print(f"  [{channel_id}] Embed deneme {attempt} hatası: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    if not m3u8_url:
        return None, None

    # 2) m3u8 URL'sine istek at, gerçek içeriği al
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                m3u8_url, headers=STREAM_HEADERS,
                timeout=TIMEOUT, allow_redirects=True
            )
            if resp.status_code == 200:
                text = resp.text
                if looks_like_m3u8(text):
                    print(f"  ✅ m3u8 içeriği alındı ({len(text)} byte)")
                    return m3u8_url, text
                else:
                    print(f"  ⚠️  200 döndü ama m3u8 formatında değil.")
                    print(f"     İlk 200 char: {text[:200]!r}")
            else:
                print(f"  [{channel_id}] m3u8 deneme {attempt}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [{channel_id}] m3u8 deneme {attempt} hatası: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    return m3u8_url, None


# ---------------------------------------------------------------
# ANA
# ---------------------------------------------------------------
def main():
    if not os.path.exists(CHANNELS_FILE):
        print(f"❌ {CHANNELS_FILE} yok.")
        sys.exit(1)

    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    channels = data.get("channels", [])
    if not channels:
        print("❌ Kanal listesi boş.")
        sys.exit(1)

    os.makedirs(PLAYLIST_DIR, exist_ok=True)

    success = 0
    fail = 0
    partial = 0  # URL var ama içerik yok

    for ch in channels:
        cid = str(ch.get("id", "")).strip()
        slug = ch.get("slug") or cid
        name = ch.get("name", cid)
        if not cid:
            continue

        print(f"\n📡 {name} (id={cid})")

        m3u8_url, content = fetch_channel_m3u8_content(cid)

        if content:
            # ✅ Gerçek m3u8 içeriği — olduğu gibi yaz
            out_path = os.path.join(PLAYLIST_DIR, f"{slug}.m3u8")
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content if content.endswith("\n") else content + "\n")
            print(f"  💾 Yazıldı: playlist/{slug}.m3u8")

            # İstenirse id.m3u8 de yaz
            if slug != cid:
                id_path = os.path.join(PLAYLIST_DIR, f"{cid}.m3u8")
                with open(id_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content if content.endswith("\n") else content + "\n")

            success += 1

        elif m3u8_url:
            # ⚠️ URL var, içerik yok → 403 vs. Sorunu görünür kıl.
            out_path = os.path.join(PLAYLIST_DIR, f"{slug}.error.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(
                    f"# m3u8 içeriği alınamadı (403 vs.)\n"
                    f"# Bulunan URL: {m3u8_url}\n"
                    f"# Zaman: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
            print(f"  ⚠️  İçerik alınamadı, playlist/{slug}.error.txt yazıldı.")
            partial += 1
        else:
            print(f"  ❌ Embed'den m3u8 URL'si bile alınamadı.")
            fail += 1

    print(f"\n📊 Özet: {success} tam başarılı, {partial} kısmi (URL var/içerik yok), {fail} başarısız.")

    # Hiç tam başarı yoksa fail et
    if success == 0:
        print("❌ Hiçbir kanal için m3u8 içeriği alınamadı.")
        sys.exit(1)


if __name__ == "__main__":
    main()

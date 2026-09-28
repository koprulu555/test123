#!/usr/bin/env python3
"""
canlitv.you embed sayfalarından m3u8 URL'lerini çeker ve
playlist/ klasörüne id.m3u8 olarak kaydeder.
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

# Tercih edilen domain: you
EMBED_DOMAIN = "https://www.canlitv.you"

# İstek başlıkları (tarayıcı taklidi)
HEADERS = {
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

TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 3


# ---------------------------------------------------------------
# M3U8 AYIKLAMA
# ---------------------------------------------------------------
def extract_m3u8(html: str):
    """
    HTML içeriğinden m3u8 URL'sini çıkarır.
    Birden fazla desen dener (jwplayer, video, source, bare URL).
    """
    if not html:
        return None

    # HTML yorumlarını temizle
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    patterns = [
        # 1) jwplayer file: "...m3u8" (en yaygın)
        r"""file\s*:\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 2) file = "...m3u8"
        r"""file\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 3) src="...m3u8"
        r"""src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 4) data-src="...m3u8"
        r"""data-src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 5) data-lazy-src="...m3u8"
        r"""data-lazy-src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 6) player.src("...m3u8")
        r"""player\.(?:src|source)\s*\(\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 7) hls.loadSource("...m3u8")
        r"""(?:hls|video)\.(?:loadSource|src)\s*\(\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 8) source: '...m3u8'
        r"""['"]source['"]\s*:\s*['"]([^'"]*\.m3u8[^'"]*)['"]""",
        # 9) url: '...m3u8'
        r"""['"]url['"]\s*:\s*['"]([^'"]*\.m3u8[^'"]*)['"]""",
        # 10) bare URL (en son çare)
        r"""(https?://[^\s"'<>\\]+\.m3u8[^\s"'<>\\]*)""",
        # 11) <source src="...m3u8">
        r"""<source\s+[^>]*src\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
        # 12) href="...m3u8"
        r"""href\s*=\s*["']([^"']*\.m3u8[^"']*)["']""",
    ]

    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            url = m.group(1).strip()
            # Sondaki kirli karakterleri temizle
            url = re.sub(r'[,\s"\'<>]+$', "", url)
            if len(url) > 20:
                return url

    return None


# ---------------------------------------------------------------
# TEK KANAL ÇEKME
# ---------------------------------------------------------------
def fetch_channel_stream(channel_id: str):
    """
    Verilen id için embed sayfasını çeker, m3u8 URL'sini ayıklar.
    Başarılıysa URL, değilse None döner.
    """
    # Önce online.php?onay=1 ile oturum başlat (bazı sitelerde gerekli)
    try:
        onay_url = (
            f"https://canlitv.you/online/online.php"
            f"?sayfa={channel_id}&tur=1&ref=0&onay=1"
        )
        requests.get(onay_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        time.sleep(0.5)
    except Exception:
        pass  # onay başarısız olsa da devam et

    embed_url = f"{EMBED_DOMAIN}/embed/?id={channel_id}&autoplay=1&muted=1"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                embed_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
            html = resp.text

            m3u8_url = extract_m3u8(html)
            if m3u8_url:
                return m3u8_url

            print(f"  [{channel_id}] Deneme {attempt}: HTML alındı ama m3u8 bulunamadı.")
        except Exception as e:
            print(f"  [{channel_id}] Deneme {attempt} hatası: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    return None


# ---------------------------------------------------------------
# ANA FONKSİYON
# ---------------------------------------------------------------
def main():
    # Kanalları oku
    if not os.path.exists(CHANNELS_FILE):
        print(f"❌ {CHANNELS_FILE} bulunamadı.")
        sys.exit(1)

    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    channels = data.get("channels", [])
    if not channels:
        print("❌ channels.json içinde kanal yok.")
        sys.exit(1)

    # Playlist klasörünü oluştur
    os.makedirs(PLAYLIST_DIR, exist_ok=True)

    success = 0
    fail = 0

    for ch in channels:
        cid = str(ch.get("id", "")).strip()
        slug = ch.get("slug") or cid  # slug yoksa id kullan
        name = ch.get("name", cid)

        if not cid:
            print("⚠️  ID eksik, atlanıyor.")
            continue

        print(f"📡 {name} (id={cid}) çekiliyor...")
        m3u8_url = fetch_channel_stream(cid)

        if not m3u8_url:
            print(f"  ❌ {name} için m3u8 alınamadı.")
            fail += 1
            continue

        # Dosyayı yaz: playlist/<slug>.m3u8
        # İçerik doğrudan m3u8 URL'si olsun (player direkt oynatabilsin)
        out_path = os.path.join(PLAYLIST_DIR, f"{slug}.m3u8")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(m3u8_url + "\n")

        print(f"  ✅ {slug}.m3u8 yazıldı -> {m3u8_url[:80]}...")
        success += 1

        # Aynı id için id.m3u8 de oluştur (istenirse)
        if slug != cid:
            id_path = os.path.join(PLAYLIST_DIR, f"{cid}.m3u8")
            with open(id_path, "w", encoding="utf-8") as f:
                f.write(m3u8_url + "\n")

    print(f"\n📊 Özet: {success} başarılı, {fail} başarısız.")

    # Hiç başarı yoksa hata kodu ile çık (workflow fail olsun)
    if success == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

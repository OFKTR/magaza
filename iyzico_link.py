"""
iyzico Link eşitleyici.

Her ürünün stokta olan her numarası için bir iyzico ödeme linki tutar:
  - Link yoksa oluşturur (ürün fotoğrafıyla).
  - Fiyat veya stok değiştiyse günceller.
  - Numara stoktan çıktıysa linki PASİF yapar, geri gelirse AKTİF yapar.
Kayıt tutmaya gerek yoktur: her çalışmada iyzico'daki linkler listelenir ve
açıklamadaki "Ürün kodu: X / Numara: Y" satırından eşleştirilir.

Gerekli ortam değişkenleri (GitHub Secrets):
  IYZICO_API_KEY, IYZICO_SECRET_KEY
İsteğe bağlı:
  IYZICO_BASE_URL  (deneme ortamı için https://sandbox-api.iyzipay.com)
"""
import base64, hashlib, hmac, json, os, random, re, struct, time, urllib.request, urllib.error, zlib

KEY = os.environ.get("IYZICO_API_KEY", "").strip()
SECRET = os.environ.get("IYZICO_SECRET_KEY", "").strip()
# Adres girilmemişse anahtarın türüne göre seçilir: sandbox- ile başlıyorsa deneme ortamı.
BASE = (os.environ.get("IYZICO_BASE_URL", "").strip()
        or ("https://sandbox-api.iyzipay.com" if KEY.startswith("sandbox-") else "https://api.iyzipay.com")).rstrip("/")
ANAHTAR_RE = re.compile(r"Ürün kodu:\s*(.+?)\s*/\s*Numara:\s*(\S+)")


def aktif_mi():
    return bool(KEY and SECRET)


IMZADA_SORGU = False  # iyzico imzaya sorgu kısmını (?page=..) istiyorsa otomatik True olur


def tani():
    """Anahtarları göstermeden olası kurulum hatalarını yazdırır."""
    sorun = []
    print(f"iyzico adresi: {BASE}")
    print(f"API anahtarı: {len(KEY)} karakter, 'sandbox-' ile başlıyor: {KEY.startswith('sandbox-')}")
    print(f"Güvenlik anahtarı: {len(SECRET)} karakter, 'sandbox-' ile başlıyor: {SECRET.startswith('sandbox-')}")
    if KEY.startswith("sandbox-") != ("sandbox" in BASE):
        sorun.append("Deneme (sandbox) anahtarı canlı adresle ya da canlı anahtar deneme adresiyle kullanılıyor. "
                     "Deneme anahtarı için IYZICO_BASE_URL = https://sandbox-api.iyzipay.com olmalı.")
    if KEY.startswith("sandbox-") != SECRET.startswith("sandbox-"):
        sorun.append("Anahtarlardan biri deneme, diğeri canlı ortama ait görünüyor.")
    if KEY and KEY == SECRET:
        sorun.append("API anahtarı ile güvenlik anahtarı aynı girilmiş.")
    for s in sorun:
        print("  OLASI SORUN:", s)
    return sorun


def _imza(yol, govde):
    rnd = str(int(time.time() * 1000)) + str(random.randint(100000000, 999999999))
    if not IMZADA_SORGU:
        yol = yol.split("?", 1)[0]
    payload = rnd + yol + (govde or "")
    sig = hmac.new(SECRET.encode(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = f"apiKey:{KEY}&randomKey:{rnd}&signature:{sig}"
    return rnd, "IYZWSv2 " + base64.b64encode(auth.encode("utf-8")).decode()


def istek(metod, yol, veri=None):
    global IMZADA_SORGU
    try:
        return _istek(metod, yol, veri)
    except RuntimeError as e:
        if "?" in yol and "uthentication" in str(e) and not IMZADA_SORGU:
            IMZADA_SORGU = True
            try:
                sonuc = _istek(metod, yol, veri)
                print("iyzico: imza sorgu kısmıyla kabul edildi, bu yöntemle devam ediliyor.")
                return sonuc
            except RuntimeError:
                IMZADA_SORGU = False
        raise


def _istek(metod, yol, veri=None):
    govde = json.dumps(veri, ensure_ascii=False, separators=(",", ":")) if veri is not None else ""
    rnd, auth = _imza(yol, govde)
    req = urllib.request.Request(BASE + yol, method=metod, data=govde.encode("utf-8") if govde else None,
                                 headers={"Authorization": auth, "x-iyzi-rnd": rnd,
                                          "Content-Type": "application/json", "Accept": "application/json"})
    for deneme in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                cevap = json.loads(r.read().decode("utf-8") or "{}")
            break
        except urllib.error.HTTPError as e:
            try:
                cevap = json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                cevap = {"status": "failure", "errorMessage": f"HTTP {e.code}"}
            if e.code >= 500 and deneme < 2:
                time.sleep(2 + deneme * 3)
                continue
            break
    if cevap.get("status") != "success":
        raise RuntimeError(f"iyzico {metod} {yol}: {cevap.get('errorCode','')} {cevap.get('errorMessage', cevap)}")
    return cevap.get("data") or {}


def _png(r=214, g=180, b=138, w=600):
    """Fotoğrafı olmayan ürünler için düz renkli bir PNG üretir (iyzico görsel istiyor)."""
    satir = b"\x00" + bytes([r, g, b]) * w
    ham = zlib.compress(satir * w, 9)
    def parca(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + parca(b"IHDR", struct.pack(">IIBBBBB", w, w, 8, 2, 0, 0, 0))
            + parca(b"IDAT", ham) + parca(b"IEND", b""))


_gorsel_onbellek = {}


def gorsel_b64(urun):
    url = (urun.get("resim") or [None])[0]
    if url in _gorsel_onbellek:
        return _gorsel_onbellek[url]
    veri = None
    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AdimMagaza"})
            with urllib.request.urlopen(req, timeout=30) as r:
                veri = r.read()
            if len(veri) > 4_000_000:
                veri = None
        except Exception:
            veri = None
    sonuc = base64.b64encode(veri or _png()).decode()
    _gorsel_onbellek[url] = sonuc
    return sonuc


def mevcut_linkler():
    """iyzico'daki tüm linkleri (kod, numara) -> link bilgisi olarak döndürür."""
    linkler, sayfa = {}, 1
    while True:
        d = istek("GET", f"/v2/iyzilink/products?locale=tr&page={sayfa}&count=100")
        for it in d.get("items", []):
            m = ANAHTAR_RE.search(it.get("description", "") or "")
            if m:
                linkler[(m.group(1), m.group(2))] = it
        if sayfa >= int(d.get("pageCount") or 1):
            break
        sayfa += 1
    return linkler


def link_adi(urun, beden):
    """iyzico link adı en fazla 50 karakter olabilir: 'CST Loafer Pelle Erkek Ayakkabı - 42 No'."""
    ek = f" - {beden} No"
    kisa = re.sub(r"^\S+\s+-\s+", "", urun["ad"]).strip()
    return kisa[: 50 - len(ek)].rstrip(" -") + ek


def _govde(urun, beden, stok, ayar, gorselli):
    g = {
        "locale": "tr",
        "conversationId": f"{urun['kod']}-{beden}",
        "name": link_adi(urun, beden),
        "description": (f"{urun.get('marka','')} {urun['ad']}. Renk: {urun.get('renk') or '-'}. "
                        f"Ücretsiz kargo. Ürün kodu: {urun['kod']} / Numara: {beden}").strip(),
        "price": f"{urun['fiyat']:.2f}",
        "currencyCode": "TRY",
        "addressIgnorable": False,
        "installmentRequested": bool(ayar.get("taksit", False)),
        "stockEnabled": True,
        "stockCount": int(stok),
    }
    if gorselli:
        g["encodedImageFile"] = gorsel_b64(urun)
    return g


def _durum(it):
    return str(it.get("productStatus") or it.get("status") or "").upper()


def esitle(urunler, ayar, tum_kodlar):
    """urunler: sitede gösterilecek (stoklu) ürünler. tum_kodlar: XML'deki tüm ürün kodları."""
    limit = int(ayar.get("iyzico_tur_basina_en_fazla_yeni", 300))
    tani()
    mevcut = mevcut_linkler()
    print(f"iyzico: {len(mevcut)} mevcut link bulundu")
    satilan = [(k, int(it.get("soldCount") or 0)) for k, it in mevcut.items() if int(it.get("soldCount") or 0) > 0]
    if satilan:
        print(f"iyzico SATIŞLAR: {len(satilan)} numarada toplam {sum(n for _, n in satilan)} satış")
        for (kod, beden), n in sorted(satilan)[:30]:
            print(f"  - {kod} / {beden} numara: {n} adet")
    else:
        print("iyzico SATIŞLAR: henüz satış yok")
    sayac = {"yeni": 0, "guncel": 0, "pasif": 0, "aktif": 0, "hata": 0}
    deneme = 0
    istenen = set()

    for u in urunler:
        for b in u["beden"]:
            anahtar = (u["kod"], b["b"])
            if b["s"] <= 0:
                continue
            istenen.add(anahtar)
            it = mevcut.get(anahtar)
            try:
                if not it:
                    if deneme >= limit:
                        continue
                    deneme += 1
                    d = istek("POST", "/v2/iyzilink/products", _govde(u, b["b"], b["s"], ayar, True))
                    b["l"] = d.get("url", "")
                    sayac["yeni"] += 1
                    time.sleep(0.1)
                    continue
                tok = it.get("token")
                if _durum(it) == "PASSIVE":
                    istek("PATCH", f"/v2/iyzilink/products/{tok}/status/ACTIVE")
                    sayac["aktif"] += 1
                eski_fiyat = float(it.get("price") or 0)
                eski_stok = int(it.get("stockCount") or 0)
                if abs(eski_fiyat - u["fiyat"]) > 0.009 or eski_stok != b["s"]:
                    istek("PUT", f"/v2/iyzilink/products/{tok}", _govde(u, b["b"], b["s"], ayar, False))
                    sayac["guncel"] += 1
                    time.sleep(0.15)
                b["l"] = it.get("url", "")
            except Exception as e:
                sayac["hata"] += 1
                if sayac["hata"] <= 20:
                    print("  uyarı:", e)

    # Stoktan çıkan veya katalogdan kalkan numaraların linklerini kapat
    for anahtar, it in mevcut.items():
        if anahtar in istenen or _durum(it) == "PASSIVE":
            continue
        try:
            istek("PATCH", f"/v2/iyzilink/products/{it.get('token')}/status/PASSIVE")
            sayac["pasif"] += 1
        except Exception as e:
            sayac["hata"] += 1
            print("  uyarı:", e)

    print(f"iyzico: {sayac['yeni']} yeni, {sayac['guncel']} güncellenen, {sayac['aktif']} yeniden açılan, "
          f"{sayac['pasif']} kapatılan link, {sayac['hata']} hata")
    return sayac

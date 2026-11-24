#!/usr/bin/env python3
"""
Adım Ayakkabı - katalog güncelleyici.

Bayinin XML linkini indirir, ürünleri okur, ayarlar.json'daki kâr kuralına göre
satış fiyatını hesaplar, stoğu olmayanları gizler ve site/urunler.json dosyasını yazar.

Kullanım:
  XML_URL="https://...xml-linkin..." python3 guncelle.py     (gerçek XML)
  python3 guncelle.py                                       (XML_URL yoksa ornek.xml kullanılır)

Sadece Python'un kendi kütüphanelerini kullanır; kurulacak bir şey yoktur.
"""
import json, math, os, re, sys, html, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

KOK = os.path.dirname(os.path.abspath(__file__))
AYAR = json.load(open(os.path.join(KOK, "ayarlar.json"), encoding="utf-8"))
ET_ = AYAR["etiketler"]


def ad(el):
    """Etiket adını isim alanı (namespace) olmadan, küçük harfle döndürür."""
    t = el.tag
    if not isinstance(t, str):
        return ""
    return t.split("}", 1)[-1].lower()


def metin(el):
    return (el.text or "").strip() if el is not None else ""


def bul(el, adaylar, derin=False):
    """el'in altında adaylar listesindeki ilk etiketin metnini döndürür."""
    kucuk = [a.lower() for a in adaylar]
    cocuklar = list(el.iter())[1:] if derin else list(el)
    for a in kucuk:
        for c in cocuklar:
            if (ad(c) == a or c.attrib.get("name", "").lower() == a) and metin(c):
                return metin(c)
    # Değer etiketin özelliği (attribute) olarak da gelebilir: <Urun Kod="..">
    for k, v in el.attrib.items():
        if k.lower() in kucuk and v.strip():
            return v.strip()
    return ""


def sayi(s):
    """'1.250,00 TL', '1250.00', '1250' gibi metinleri sayıya çevirir."""
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def temiz_aciklama(s):
    s = html.unescape(s or "")
    s = re.sub(r"<\s*br\s*/?>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()[:1500]


def satis_fiyati(alis, kod):
    """
    Satış fiyatını, her şey ödendikten sonra cebine net_kar_tl kalacak şekilde hesaplar.

    Kasaya giren   = fiyat x (1 - iyzico komisyonu)
    Bayiye ödenen  = alış (KDV dahil)
    Devlete KDV    = satıştaki KDV - alıştaki KDV
    Cebe kalan     = kasaya giren - bayiye ödenen - devlete KDV - kargo  = net_kar_tl
    (Gelir vergisi bu hesaba dahil değildir.)
    """
    if kod in AYAR.get("ozel_fiyatlar", {}):
        return int(AYAR["ozel_fiyatlar"][kod])
    k = AYAR.get("kdv_orani", 10) / 100
    alis_haric = alis / (1 + k) if AYAR.get("alis_kdv_dahil", False) else alis
    kom = AYAR.get("odeme_komisyon_yuzde", 4) / 100
    net = AYAR.get("net_kar_tl", AYAR.get("kar_tl", 500))
    f = (alis_haric + net + AYAR.get("kargo_payi_tl", 0)) / (1 - kom - k / (1 + k))
    y = AYAR.get("yuvarla", 50) or 1
    return int(math.ceil(f / y) * y - (1 if y >= 10 else 0))  # ör. 1549, 1599


def cebe_kalan(fiyat, alis):
    k = AYAR.get("kdv_orani", 10) / 100
    alis_haric = alis / (1 + k) if AYAR.get("alis_kdv_dahil", False) else alis
    kom = AYAR.get("odeme_komisyon_yuzde", 4) / 100
    return fiyat * (1 - kom) - alis_haric * (1 + k) - (fiyat * k / (1 + k) - alis_haric * k) - AYAR.get("kargo_payi_tl", 0)


def resimler(el):
    bas = tuple(ET_["resim_baslar"])
    out = []
    for c in el.iter():
        t = metin(c)
        if ad(c).startswith(bas) and t.startswith("http"):
            out.append(t)
        for k, v in c.attrib.items():
            if k.lower().startswith(bas) and v.startswith("http"):
                out.append(v)
    goruldu, sonuc = set(), []
    for u in out:
        if u not in goruldu:
            goruldu.add(u)
            sonuc.append(u)
    return sonuc[:10]


def bedenler(el, toplam_stok):
    var_adlari = [a.lower() for a in ET_["varyant"]]
    liste = []
    for v in el.iter():
        if ad(v) in var_adlari:
            b = bul(v, ET_["beden"], derin=True)
            if not b:
                continue
            st = bul(v, ET_["stok"], derin=True)
            liste.append({"b": b, "s": int(sayi(st)) if st else toplam_stok})
    if not liste:
        tek = bul(el, ET_["bedenler_tek_alan"], derin=True)
        if tek:
            for p in re.split(r"[,;|/]", tek):
                p = p.strip()
                if p:
                    liste.append({"b": p, "s": toplam_stok if toplam_stok else 1})
    # Aynı numara birden fazla geldiyse stokları topla
    birlesik = {}
    for x in liste:
        birlesik[x["b"]] = birlesik.get(x["b"], 0) + max(0, x["s"])
    def sirala(k):
        n = sayi(k)
        return (0, n) if n else (1, k)
    return [{"b": k, "s": birlesik[k]} for k in sorted(birlesik, key=sirala)]


def tr_baslik(s):
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:] for w in s.split())


def kategori_duzelt(k):
    k = re.split(r"\s*[>/|]\s*", k)[-1] if k else ""
    return tr_baslik(k.strip()) if k.strip() else "Diğer"


def xml_oku():
    url = os.environ.get("XML_URL", "").strip()
    if url:
        print("XML indiriliyor...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AdimMagaza"})
        with urllib.request.urlopen(req, timeout=90) as r:
            veri = r.read()
        print(f"İndirildi: {len(veri)//1024} KB")
        return veri, False
    print("XML_URL tanımlı değil, ornek.xml kullanılıyor.")
    return open(os.path.join(KOK, "ornek.xml"), "rb").read(), True


def main():
    veri, ornek = xml_oku()
    kok = ET.fromstring(veri)
    urun_adlari = [a.lower() for a in ET_["urun"]]
    gizli_kat = {k.lower() for k in AYAR.get("gizlenecek_kategoriler", [])}
    gizli_kod = set(AYAR.get("gizlenecek_kodlar", []))
    mnorm = lambda m: m.upper().replace("İ", "I").replace("ı", "I").strip()
    markalar = {mnorm(m) for m in AYAR.get("sadece_markalar", [])}
    tum_kodlar = set()

    urunler, atlanan, ornek_kar = [], {"stoksuz": 0, "fiyatsiz": 0, "gizli": 0}, []
    for el in kok.iter():
        if ad(el) not in urun_adlari:
            continue
        kod = bul(el, ET_["kod"])
        isim = bul(el, ET_["ad"])
        if not kod or not isim:
            continue
        tum_kodlar.add(kod)
        kat = kategori_duzelt(bul(el, ET_["kategori"], derin=True))
        marka = bul(el, ET_["marka"], derin=True)
        if (kod in gizli_kod or kat.lower() in gizli_kat
                or (markalar and mnorm(marka) not in markalar)):
            atlanan["gizli"] += 1
            continue
        alis = sayi(bul(el, ET_["alis"]))
        if alis <= 0:
            atlanan["fiyatsiz"] += 1
            continue
        st_txt = bul(el, ET_["stok"])
        toplam = int(sayi(st_txt)) if st_txt else 0
        bd = bedenler(el, toplam)
        if bd:
            toplam = sum(x["s"] for x in bd)
        if toplam < AYAR.get("en_az_stok", 1):
            atlanan["stoksuz"] += 1
            continue
        fiyat = satis_fiyati(alis, kod)
        ornek_kar.append(cebe_kalan(fiyat, alis))
        psf = sayi(bul(el, ET_["psf"]))
        urunler.append({
            "id": re.sub(r"[^A-Za-z0-9-]", "", kod) or str(len(urunler)),
            "kod": kod,
            "ad": isim,
            "kat": kat,
            "marka": marka,
            "renk": bul(el, ET_["renk"], derin=True),
            "fiyat": fiyat,
            "psf": int(psf) if AYAR.get("psf_goster", False) and psf > fiyat else 0,
            "resim": resimler(el),
            "beden": bd,
            "stok": toplam,
            "acik": temiz_aciklama(bul(el, ET_["aciklama"], derin=True)),
        })

    if not urunler:
        print("HATA: Hiç ürün okunamadı. ayarlar.json içindeki 'etiketler' kısmını XML'e göre düzenleyin.")
        sys.exit(1)

    odeme = False
    try:
        import iyzico_link
        if not AYAR.get("satis_acik", False):
            print("Satış kapalı (ayarlar.json: satis_acik=false). Site sadece vitrin olarak yayınlanıyor.")
        elif iyzico_link.aktif_mi():
            iyzico_link.esitle(urunler, AYAR, tum_kodlar)
            odeme = True
        else:
            print("iyzico anahtarları tanımlı değil; ödeme linkleri oluşturulmadı.")
    except Exception as e:
        print("UYARI: iyzico eşitlemesi tamamlanamadı:", e)
        odeme = any(b.get("l") for u in urunler for b in u["beden"])

    tr = timezone(timedelta(hours=3))
    meta = {
        "magaza": AYAR["magaza_adi"],
        "tel": AYAR.get("telefon_yazisi", ""),
        "eposta": AYAR.get("eposta", ""),
        "odeme": odeme,
        "test": odeme and os.environ.get("IYZICO_API_KEY", "").strip().startswith("sandbox-"),
        "sehir": AYAR.get("sehir", ""),
        "guncel": datetime.now(tr).strftime("%d.%m.%Y %H:%M"),
        "ornek": ornek,
    }
    cikti = {"meta": meta, "urunler": urunler}
    yol = os.path.join(KOK, "site", "urunler.json")
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(cikti, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Tamam: {len(urunler)} ürün yazıldı -> site/urunler.json")
    if ornek_kar:
        print(f"Çift başı cebe kalan (gelir vergisi öncesi): en az {min(ornek_kar):.0f} TL, ortalama {sum(ornek_kar)/len(ornek_kar):.0f} TL")
    print(f"Atlanan: {atlanan['stoksuz']} stoksuz, {atlanan['fiyatsiz']} fiyatsız, {atlanan['gizli']} gizlenen")

    # Ürünleri sayfanın içine gömerek site/index.html'i üret (dosya çift tıklanınca da çalışır)
    sablon = open(os.path.join(KOK, "sablon.html"), encoding="utf-8").read()
    gomulu = json.dumps(cikti, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    sayfa = sablon.replace("<!--VERI-->", f"<script>window.__VERI={gomulu};</script>")
    if AYAR.get("arama_motorundan_gizle", True):
        sayfa = sayfa.replace("<!--ROBOTS-->", '<meta name="robots" content="noindex, nofollow">')
    with open(os.path.join(KOK, "site", "index.html"), "w", encoding="utf-8") as f:
        f.write(sayfa)
    print("site/index.html üretildi")

if __name__ == "__main__":
    main()

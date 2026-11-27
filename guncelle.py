#!/usr/bin/env python3
"""
NOVER - katalog güncelleyici.

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


def _sade(s):
    s = (s or "").upper()
    for a, b in {"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C", "ı": "I"}.items():
        s = s.replace(a, b)
    return re.sub(r"[^A-Z0-9]", "", s)


KAYNAK = {}  # o an okunan tedarikçinin ayarları


def net_kar(ad="", kat=""):
    """Önce ürün adına göre kâr kuralı, sonra tedarikçinin kârı, en son genel kâr."""
    metin = _sade(f"{ad} {kat}")
    for kural in AYAR.get("kar_kurallari", []):
        if any(_sade(k) in metin for k in kural.get("icerir", [])):
            return kural["net_kar_tl"]
    return KAYNAK.get("net_kar_tl", AYAR.get("net_kar_tl", AYAR.get("kar_tl", 500)))


def _kdv(kdv):
    return (kdv if kdv is not None else KAYNAK.get("kdv_orani", AYAR.get("kdv_orani", 10))) / 100


def satis_fiyati(alis, kod, ad="", kat="", kdv=None):
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
    k = _kdv(kdv)
    alis_haric = alis / (1 + k) if KAYNAK.get("alis_kdv_dahil", AYAR.get("alis_kdv_dahil", False)) else alis
    kom = AYAR.get("odeme_komisyon_yuzde", 4) / 100
    net = net_kar(ad, kat)
    f = (alis_haric + net + AYAR.get("kargo_payi_tl", 0)) / (1 - kom - k / (1 + k))
    y = AYAR.get("yuvarla", 50) or 1
    return int(math.ceil(f / y) * y - (1 if y >= 10 else 0))  # ör. 1549, 1599


def cebe_kalan(fiyat, alis, kdv=None):
    k = _kdv(kdv)
    alis_haric = alis / (1 + k) if KAYNAK.get("alis_kdv_dahil", AYAR.get("alis_kdv_dahil", False)) else alis
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


def on_ekli(kod):
    """Bayi kuralı: kodların başına en az 5 haneli ön ek (ör. NOVER)."""
    on = AYAR.get("kod_on_eki", "NOVER")
    if not kod or kod == "0":
        return ""
    return kod if kod.upper().startswith(on.upper()) else f"{on}{kod}"


def _harf_esnek(s):
    """Marka adını büyük/küçük ve İ/I/ı/i farkı gözetmeden yakalayan düzenli ifade."""
    out = ""
    for ch in s:
        if ch in "İIıi":
            out += "[İIıii̇]"
        else:
            out += f"[{re.escape(ch.upper())}{re.escape(ch.lower())}]" if ch.isalpha() else re.escape(ch)
    return out


def marka_temizle(s, xml_marka=""):
    """Tedarikçinin marka adlarını metinden siler (bayi kuralı: XML markası kullanılmaz)."""
    adlar = set(AYAR.get("gizlenecek_marka_adlari", []))
    if xml_marka and xml_marka.upper() not in (AYAR.get("marka", ""), ""):
        adlar.add(xml_marka)
    for a in sorted(adlar, key=len, reverse=True):
        if a.strip():
            s = re.sub(r"(?<!\w)" + _harf_esnek(a.strip()) + r"(?!\w)", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"(^|\n)[ \t]*[-–·,:]+[ \t]*", r"\1", s)
    return s.strip()


def tr_baslik(s):
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:] for w in s.split())


def kategori_duzelt(k):
    k = re.split(r"\s*[>/|]\s*", k)[-1] if k else ""
    return tr_baslik(k.strip()) if k.strip() else "Diğer"


def xml_oku(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NoverMagaza"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def kaynaklari_al():
    """ayarlar.json'daki tedarikçi listesini, linki tanımlı olanlarla döndürür."""
    liste = AYAR.get("kaynaklar") or [{"ad": "Ana tedarikçi", "xml_env": "XML_URL"}]
    hazir = []
    for k in liste:
        url = os.environ.get(k.get("xml_env", ""), "").strip()
        if url:
            hazir.append((k, url))
        else:
            print(f"{k.get('ad')}: {k.get('xml_env')} tanımlı değil, atlanıyor.")
    return hazir


def kaynak_oku(kok, urunler, atlanan, ornek_kar, tum_kodlar, kural_ref, gorulen_id):
    global ET_
    ET_ = {**AYAR["etiketler"], **KAYNAK.get("etiketler", {})}
    urun_adlari = [a.lower() for a in ET_["urun"]]
    gizli_kat = {k.lower() for k in AYAR.get("gizlenecek_kategoriler", [])}
    gizli_kod = set(AYAR.get("gizlenecek_kodlar", []))
    mnorm = lambda m: m.upper().replace("İ", "I").replace("ı", "I").strip()
    markalar = {mnorm(m) for m in AYAR.get("sadece_markalar", [])}
    once = len(urunler)
    for el in kok.iter():
        if ad(el) not in urun_adlari:
            continue
        kod = bul(el, ET_["kod"])
        isim = bul(el, ET_["ad"])
        if not kod or not isim:
            continue
        tum_kodlar.add(kod)
        kat = KAYNAK.get("kategori") or kategori_duzelt(bul(el, ET_["kategori"], derin=True))
        marka = bul(el, ET_["marka"], derin=True) or KAYNAK.get("marka", "")
        if (kod in gizli_kod or kat.lower() in gizli_kat
                or (markalar and KAYNAK.get("marka_filtresi", True) and mnorm(marka) not in markalar)):
            atlanan["gizli"] += 1
            continue
        alis = sayi(bul(el, ET_["alis"]))
        if alis <= 0:
            atlanan["fiyatsiz"] += 1
            continue
        kdv_txt = bul(el, ET_.get("kdv", []))
        kdv = sayi(kdv_txt) if kdv_txt else None
        esik = KAYNAK.get("en_az_alis_kdv_dahil_tl")
        if esik:
            kdvli = alis if KAYNAK.get("alis_kdv_dahil", AYAR.get("alis_kdv_dahil", False)) else alis * (1 + _kdv(kdv))
            if kdvli < esik:
                atlanan["ucuz"] += 1
                continue
        st_txt = bul(el, ET_["stok"])
        toplam = int(sayi(st_txt)) if st_txt else 0
        bd = bedenler(el, toplam)
        if bd:
            toplam = sum(x["s"] for x in bd)
        elif toplam > 0:
            bd = [{"b": "Standart", "s": toplam}]  # saat, kemer gibi numarasız ürünler
        if toplam < AYAR.get("en_az_stok", 1):
            atlanan["stoksuz"] += 1
            continue
        fiyat = satis_fiyati(alis, kod, isim, kat, kdv)
        ornek_kar.append(cebe_kalan(fiyat, alis, kdv))
        if net_kar(isim, kat) != AYAR.get("net_kar_tl", 500):
            kural_ref[0] += 1
        psf = sayi(bul(el, ET_["psf"]))
        skod = on_ekli(kod)
        model = on_ekli(bul(el, ET_.get("model", [])) or kod)
        uid = re.sub(r"[^A-Za-z0-9-]", "", skod) or str(len(urunler))
        if uid in gorulen_id:
            uid = f"{uid}-{len(urunler)}"
        gorulen_id.add(uid)
        urunler.append({
            "id": uid,
            "kod": kod,          # bayinin ham kodu: yalnızca iyzico eşleştirmesi için, sitede gösterilmez
            "skod": skod,        # sitede görünen ürün kodu (ön ekli)
            "model": model,      # ön ekli model kodu (Mpn): aynı modelin renklerini birbirine bağlar
            "barkod": on_ekli(bul(el, ET_.get("barkod", []))),
            "ad": marka_temizle(isim, marka),
            "kat": kat,
            "marka": AYAR.get("marka", AYAR["magaza_adi"]),
            "renk": bul(el, ET_["renk"], derin=True),
            "fiyat": fiyat,
            "psf": int(psf) if AYAR.get("psf_goster", False) and psf > fiyat else 0,
            "resim": resimler(el),
            "beden": bd,
            "stok": toplam,
            "acik": marka_temizle(temiz_aciklama(bul(el, ET_["aciklama"], derin=True)), marka),
        })
    print(f"{KAYNAK.get('ad', 'Tedarikçi')}: {len(urunler) - once} ürün eklendi")


def _onceki_veriyi_oku():
    """Bir önceki yayının fiyat geçmişini (iş akışı indirir) okur.
    Geçmiş dosyası yoksa yayındaki urunler.json'daki fiyatlarla başlatır."""
    gecmis = {}
    try:
        gecmis = json.load(open(os.path.join(KOK, "onceki_fiyat_gecmisi.json"), encoding="utf-8"))
    except Exception:
        pass
    if gecmis:
        return gecmis
    try:
        eski = json.load(open(os.path.join(KOK, "onceki_urunler.json"), encoding="utf-8"))
        g = eski.get("meta", {}).get("guncel", "")
        tarih = datetime.strptime(g, "%d.%m.%Y %H:%M").strftime("%Y-%m-%d")
        on = AYAR.get("kod_on_eki", "NOVER")
        for u in eski.get("urunler", []):
            i = str(u.get("id", ""))
            if not i or not u.get("fiyat"):
                continue
            k = i if i.upper().startswith(on.upper()) else f"{on}{i}"
            gecmis[k] = [[tarih, int(u["fiyat"])]]
        print(f"Fiyat geçmişi yayındaki sürümden başlatıldı ({len(gecmis)} ürün, {tarih})")
    except Exception:
        pass
    return gecmis


def fiyat_gecmisi_uygula(urunler):
    """Her ürünün günlük fiyatını kaydeder. Bugünkü fiyat, bugünden önceki son 10 günün
    en düşük fiyatından düşükse o fiyatı üstü çizili 'eski fiyat' olarak gösterir
    (Ticari Reklam ve Haksız Ticari Uygulamalar Yönetmeliği, 10 gün kuralı)."""
    if not AYAR.get("indirim_goster", True):
        return 0
    gun_say = AYAR.get("indirim_referans_gun", 10)
    en_az = AYAR.get("indirim_en_az_yuzde", 5)
    tr = timezone(timedelta(hours=3))
    bugun = datetime.now(tr).date()
    bas = (bugun - timedelta(days=gun_say)).isoformat()
    sil = (bugun - timedelta(days=45)).isoformat()
    b = bugun.isoformat()
    gecmis = _onceki_veriyi_oku()
    # Tek seferlik: eski bir yayının arşivindeki fiyatları gerçek tarihiyle geçmişe ekle
    try:
        eski = json.load(open(os.path.join(KOK, "eski_urunler.json"), encoding="utf-8"))
        tarih = open(os.path.join(KOK, "eski_urunler_tarih.txt")).read().strip()
        on = AYAR.get("kod_on_eki", "NOVER")
        n = 0
        for eu in eski.get("urunler", []):
            i = str(eu.get("id", ""))
            if not i or not eu.get("fiyat"):
                continue
            k = i if i.upper().startswith(on.upper()) else f"{on}{i}"
            kayit = gecmis.setdefault(k, [])
            if not any(x[0] == tarih for x in kayit):
                kayit.append([tarih, int(eu["fiyat"])])
                kayit.sort()
                n += 1
        print(f"Eski yayın arşivinden {n} ürünün {tarih} fiyatı geçmişe eklendi")
    except FileNotFoundError:
        pass
    except Exception as e:
        print("UYARI: eski yayın arşivi okunamadı:", e)
    yeni, say = {}, 0
    for u in urunler:
        kayit = [x for x in gecmis.get(u["id"], []) if x[0] >= sil]
        onceki = [x[1] for x in kayit if bas <= x[0] < b]
        kayit = [x for x in kayit if x[0] != b] + [[b, min([u["fiyat"]] + [x[1] for x in kayit if x[0] == b])]]
        yeni[u["id"]] = kayit
        ref = min(onceki) if onceki else 0
        if ref > u["fiyat"] and (1 - u["fiyat"] / ref) * 100 >= en_az:
            u["psf"] = int(ref)
            say += 1
        elif not AYAR.get("psf_goster", False):
            u["psf"] = 0
    with open(os.path.join(KOK, "site", "fiyat_gecmisi.json"), "w", encoding="utf-8") as f:
        json.dump(yeni, f, separators=(",", ":"))
    return say


def main():
    global KAYNAK
    urunler, atlanan, ornek_kar = [], {"stoksuz": 0, "fiyatsiz": 0, "gizli": 0, "ucuz": 0}, []
    tum_kodlar, kural_ref, gorulen_id = set(), [0], set()
    kaynaklar = kaynaklari_al()
    ornek = not kaynaklar
    if ornek:
        print("Hiç XML linki tanımlı değil, ornek.xml kullanılıyor.")
        KAYNAK = {"ad": "Örnek"}
        kaynak_oku(ET.fromstring(open(os.path.join(KOK, "ornek.xml"), "rb").read()),
                   urunler, atlanan, ornek_kar, tum_kodlar, kural_ref, gorulen_id)
    for k, url in kaynaklar:
        KAYNAK = k
        print(f"{k.get('ad')}: XML indiriliyor...")
        try:
            veri = xml_oku(url)
            print(f"{k.get('ad')}: indirildi, {len(veri)//1024} KB")
            kaynak_oku(ET.fromstring(veri), urunler, atlanan, ornek_kar, tum_kodlar, kural_ref, gorulen_id)
        except Exception as e:
            if k is (AYAR.get("kaynaklar") or [k])[0]:
                raise  # ana tedarikçi okunamazsa site eski haliyle kalsın
            print(f"UYARI: {k.get('ad')} okunamadı, bu turda atlandı: {e}")
    KAYNAK = {}
    kural_say = kural_ref[0]

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

    # Bayinin ham kodu ve barkod sadece burada (iyzico eşleştirmesi) lazım; siteye gitmez.
    for u in urunler:
        u.pop("kod", None)
        u.pop("barkod", None)

    indirim_say = fiyat_gecmisi_uygula(urunler)
    if indirim_say:
        print(f"Gerçek indirim etiketi alan ürün: {indirim_say} (son 10 günün en düşük fiyatına göre)")

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
    if kural_say:
        print(f"Özel kâr kuralına giren ürün: {kural_say}")
    if ornek_kar:
        print(f"Çift başı cebe kalan (gelir vergisi öncesi): en az {min(ornek_kar):.0f} TL, ortalama {sum(ornek_kar)/len(ornek_kar):.0f} TL")
    print(f"Atlanan: {atlanan['stoksuz']} stoksuz, {atlanan['fiyatsiz']} fiyatsız, {atlanan['gizli']} gizlenen, "
          f"{atlanan['ucuz']} ücretsiz kargo sınırının altında")

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

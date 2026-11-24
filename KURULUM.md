# NOVER: Ücretsiz, kendi kendini güncelleyen mağaza

Bu mağaza her 3 saatte bir kendiliğinden şunları yapar:

1. Bayinin XML'ini indirir (tüm ürünler, fotoğraflar, numaralar, stoklar).
2. Satış fiyatını, KDV ve iyzico kesintisi ödendikten sonra her çiftten cebine **net 500 TL** kalacak şekilde hesaplar.
3. Her modelin stokta olan **her numarası için bir iyzico ödeme linki** oluşturur. Fiyat veya stok değişince linki günceller, numara tükenince linki kapatır, stok geri gelince yeniden açar.
4. Siteyi yeniden yayınlar.

Müşteri modeli ve numarayı seçer, **"Kartla öde"** butonuna basar, iyzico'nun güvenli sayfasında adresini ve kartını girer. Para iyzico hesabına geçer, sana e-posta veya uygulama bildirimi gelir. Sen de siparişi bayi paneline girersin.

**Aylık ücret yok.** Sadece iyzico her satıştan komisyon keser.

## Klasördekiler

| Dosya | Ne işe yarar |
|---|---|
| `ayarlar.json` | Mağaza adı, iletişim, kâr, komisyon, marka seçimi |
| `guncelle.py` | XML'i okur, fiyatları hesaplar, siteyi hazırlar |
| `iyzico_link.py` | iyzico ödeme linklerini oluşturur ve günceller |
| `sablon.html` | Mağaza sayfasının tasarımı |
| `site/index.html` | Program tarafından üretilen, ürünleri içinde olan hazır sayfa. Bilgisayarında çift tıklayıp önizleyebilirsin. |
| `.github/workflows/guncelle.yml` | 3 saatte bir otomatik çalışan görev |
| `ornek.xml` | Anahtarlar girilmeden önce sitenin dolu görünmesi için örnek katalog |

## 1. iyzico hesabını hazırla

1. iyzico.com'da üye işyeri hesabı aç. Şahıs şirketin varsa **ticari** hesap aç.
2. Panelde **Link** ürününü etkinleştir.
3. **Ayarlar** bölümünden **API anahtarı** ve **Güvenlik anahtarı**nı (secret key) kopyala.
   - Bireysel hesapta API anahtarı verilmiyorsa iyzico'ya "iyzico Link API kullanmak istiyorum" diye sor.
4. Önce deneme yapmak istersen sandbox-merchant.iyzipay.com adresinden ücretsiz **deneme hesabı** açabilirsin (gerçek para çekilmez).

## 2. GitHub'a kur (bir kerelik, yaklaşık 15 dakika)

1. github.com'da ücretsiz hesap aç.
2. **+ > New repository**. Adı `magaza`, **Public**, **Create**.
3. **uploading an existing file** bağlantısına tıkla ve bu klasörün içindekileri sürükle.
   - `.github` klasörü yüklenmezse: **Add file > Create new file**, adı `.github/workflows/guncelle.yml`, içine aynı dosyanın içeriğini yapıştır.
4. **Settings > Secrets and variables > Actions > New repository secret** ile şu 3 gizli bilgiyi ekle:

| Name | Secret |
|---|---|
| `XML_URL` | Bayi XML linkin |
| `IYZICO_API_KEY` | iyzico API anahtarı |
| `IYZICO_SECRET_KEY` | iyzico güvenlik anahtarı |

   Deneme hesabıyla test etmek için ayrıca `IYZICO_BASE_URL` = `https://sandbox-api.iyzipay.com` ekle. Gerçek satışa geçince bu satırı sil.

5. **Settings > Pages > Source** kısmında **GitHub Actions** seç.
6. **Actions** sekmesi > **Katalogu guncelle ve yayinla** > **Run workflow**.

İlk çalıştırmada yüzlerce ödeme linki oluşturulacağı için iş birkaç dakika sürer. Her turda en fazla 300 yeni link açılır, gerisi sonraki turlarda tamamlanır. Linki henüz hazır olmayan numarada sitede "Bu numaranın ödemesi hazırlanıyor" yazar.

Site adresi: `https://KULLANICIADIN.github.io/magaza/`

**XML linkini ve iyzico anahtarlarını kimseyle paylaşma, sadece Secrets bölümüne yaz.** Bu bilgiler sitede görünmez.

## 3. Ayarlar (`ayarlar.json`)

GitHub'da dosyaya tıkla, kalem simgesiyle düzenle, **Commit changes** de. Site birkaç dakikada güncellenir.

| Ayar | Anlamı | Şu anki değer |
|---|---|---|
| `net_kar_tl` | KDV ve iyzico kesintisinden sonra her çiftten cebine kalacak para | 500 |
| `alis_kdv_dahil` | XML'deki `buying_price` KDV dahil mi? | false (KDV hariç kabul edildi) |
| `kdv_orani` | Alışa eklenecek KDV | 10 |
| `odeme_komisyon_yuzde` | iyzico'nun kestiği oran (komisyonun KDV'si dahil, yuvarlak) | 4 |
| `kargo_payi_tl` | Bayi kargo ücretini senden alıyorsa çift başı kargo tutarı | 0 |
| `yuvarla` | Fiyatı yukarı yuvarlar (1.529 TL yerine 1.549 TL) | 50 |
| `sadece_markalar` | Boşsa tüm markalar satılır. Örnek: `["CHEKICH"]` | boş |
| `gizlenecek_kategoriler` / `gizlenecek_kodlar` | Satmak istemediklerin | boş |
| `ozel_fiyatlar` | Bir ürüne elle fiyat. Örnek: `{"MN002F25490SH": 1799}` | örnek |
| `satis_acik` | `false` iken site sadece vitrindir, ödeme linki oluşturulmaz. `true` iken iyzico anahtarları girilmişse linkler oluşturulur. | true |
| `arama_motorundan_gizle` | `true` iken site Google'da çıkmaz. Satışa başlayınca `false` yap. | true |
| `taksit` | Müşteriye taksit seçeneği (komisyonu artırır) | false |
| `psf_goster` | XML'deki `Price` alanını üstü çizili gösterir | false |

**Örnek hesap (bayi fiyatı 880 TL olan model, satış fiyatı 1.599 TL):**

| | TL |
|---|---|
| Müşteri öder | 1.599 |
| iyzico keser (%4) | −64 |
| Bayiye ödenir (880 + %10 KDV) | −968 |
| Devlete KDV farkı (145 − 88) | −57 |
| **Cebine kalan** | **≈ 510** |

Gelir vergisi ve aylık sabit giderler (muhasebeci gibi) bu hesaba dahil değildir. Program her çalıştığında Actions kaydına "Çift başı cebe kalan" satırını yazar.

`psf_goster` neden kapalı: XML'deki `Price` alanı alışın 3 katı ve hiç satmadığın bir fiyat. Bunu "eski fiyat" diye gösterip indirim varmış gibi yapmak indirimli satış kurallarına aykırıdır.

## Sipariş gelince ne yapacaksın?

1. iyzico'dan satış bildirimi gelir. Link adında model ve numara yazar (ör. "CST Loafer ... - 42 Numara"), müşterinin adı ve adresi de oradadır.
2. Bayi panelinden o model ve numarayı müşterinin adresine sipariş et.
3. Kargo takip numarasını müşteriye SMS veya e-posta ile ilet.
4. Faturayı (e-arşiv) kes.

## Bir şey ters giderse

- **Actions sekmesinde kırmızı çarpı:** Tıkla ve hatayı oku. XML indirilemediyse site eski haliyle yayında kalır, boş görünmez.
- **"iyzico ... hata" uyarısı:** Anahtarların doğru girildiğini ve panelde Link ürününün açık olduğunu kontrol et.

## Yayına çıkmadan önce yasal kontrol listesi

- Şahıs şirketi ve vergi levhası (alıp satmak ticari kazançtır, şirket gerekir)
- e-Arşiv fatura
- **ETBİS kaydı** (Ticaret Bakanlığı)
- Sitede **Mesafeli Satış Sözleşmesi**, **Ön Bilgilendirme Formu** ve **KVKK aydınlatma metni**
- Bayilik sözleşmesinin kendi sitende satışa ve fiyat belirlemeye izin verdiğinin teyidi

## Not: GitHub Pages ve ticari kullanım

GitHub Pages kuralları sitenin esas olarak bir e-ticaret işi için kullanılmasına izin vermiyor. Kurmak ve denemek için uygundur. Satışlar başlayınca aynı `site` klasörünü ücretsiz ve ticari kullanıma izin veren **Cloudflare Pages**'e taşımak gerekir.

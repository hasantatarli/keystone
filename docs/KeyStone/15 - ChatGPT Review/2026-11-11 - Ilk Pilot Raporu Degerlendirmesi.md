# İlk pilot raporu değerlendirmesi (hc111, 2026-11-11)

İlk gerçek müşteri sistemi: Windows Server 2016, PostgreSQL 14.20, 36 CPU, 150 GB bellek, 3.2 TB veri. Kanıt offline toplandı (eski paket; index, vacuum, foreign key, unlogged tablo ve extension kontrolleri değerlendirilemedi). Raporu Hasan ve ChatGPT inceledi; bu doküman yorumları, Keystone'un verdiği kararları ve sonucu kaydeder. Rapor **referans assessment** olarak saklanır: bulgular müşteride doğrulandıkça aşağıdaki tablo doldurulur ve Keystone'un gerçek dünyadaki doğruluğu buradan ölçülür.

## Bulguların sınıflandırması

Sınıflar: **doğru bulgu**, **bağlam gerektiriyor** (bulgu doğru, karar müşterinin), **yanlış alarm**, **öneri iyileştirilmeli**. Müşteri cevabı gelene kadar "beklemede".

| Bulgu | Keystone | İlk değerlendirme | Müşteriye soru | Sınıf |
|---|---|---|---|---|
| synchronous_commit = off (configuration file) | WARNING | Yüksek öncelik; bilinçli olabilir | Bilinçli mi; uygulamanın kabul ettiği veri kaybı penceresi nedir? | beklemede |
| Bellek aşırı taahhüdü %143 (shared_buffers 98 GB, max_connections 5000, work_mem 24 MB) | WARNING | Yüksek öncelik; konfigürasyon ve iş yükü incelenmeli | Connection pooler var mı; 98 GB neden seçildi? | beklemede |
| WAL arşivleme kapalı | WARNING | Önemli; yedek ve PITR stratejisi doğrulanmalı | Yedekler nasıl alınıyor; PITR gerekiyor mu? | beklemede |
| SSL kapalı | WARNING | Önemli; bağlantı topolojisine bağlı | İstemciler aynı güvenli ağda mı? | beklemede |
| PUBLIC schema CREATE (postgres, TM_Hangfire, TM_Prod) | WARNING | Önemli | Uygulama kullanıcıları public'te nesne oluşturuyor mu? | beklemede |
| Login yapabilen superuser (adminpostgre) | WARNING | İncelenmeli | Rolün amacı ve kimin kullandığı | beklemede |
| Hata alıp kapatılmamış transaction (1 bağlantı) | WARNING | İzlenmeli; tek snapshot | Uygulama hata yolunda rollback yapıyor mu? | beklemede |
| Konfigürasyon önerileri (work_mem 5 MB, shared_buffers 38 GB…) | — | Öneri iyileştirilmeli: profil yokken hedef değil başlangıç noktası; 5000 bağlantıda kaldıraç bağlantı sayısı | İş yükü, sunucunun PostgreSQL'e ayrılmış olup olmadığı, disk tipi | öneri iyileştirilmeli (giderildi, aşağıda) |

## İnceleme maddeleri ve kararlar

| Madde | Karar | Durum |
|---|---|---|
| PostgreSQL 14'ün destek sonu raporda yok | Doğru. Major sürüm destek takvimi Dictionary'de bir referans tablosu olarak (PG-LIFE-001); ertelemenin yanlış olduğunu pilot gösterdi | Yapıldı (V059, ADR-0019): referans Dictionary değil referans verisi; internetten, referans dosyasından ya da kurulumla gelir; minor kontrolü 100 günden eski referansla değerlendirilmez |
| Windows Server 2016 desteği (Ocak 2027) | Doğru; PG-LIFE-003, aynı referans tablosuna işletim sistemi | PG-LIFE-001'den sonra |
| Replica yokken replikasyon kuralları "Sağlıklı" | **Kısmen yanlış tespit.** Gecikme ve "veri almayan replica" kuralları replica yokken zaten uygulanmaz. Bu sistemde primary'ye bağlı, Keystone'un bilmediği bir replica var (172.30.207.13, walreceiver, async, streaming); kurallar onu gördüğü için sağlıklı dedi. Asıl kusur: envanter "0 replica" dedi ve bu replica'nın değerlendirilmediği söylenmedi | Giderildi: bağlı ama tanımsız replica envanterde ve değerlendirilemeyenler listesinde görünür |
| Synchronous standby kuralı senkron replikasyon yokken "Sağlıklı" | Doğru | Giderildi: NOT_APPLICABLE |
| Arşivleme kapalıyken arşivleme hatası kuralı "Sağlıklı" | Doğru | Giderildi: NOT_APPLICABLE |
| "Son failover" kesin olay gibi | Doğru; timeline değişimi failover, switchover ya da restore olabilir | Giderildi: "Son timeline değişimi" |
| Yöntem metni offline'da yanlış | Doğru | Giderildi: toplama biçimine göre |
| "41 kontrol yapıldı" belirsiz | Doğru | Giderildi: "Tanımlı 43 kontrolden 41 tanesi bu sisteme uygulanabilir" |
| synchronous_commit ile fsync aynı cümlede | Doğru | Giderildi: V058, anlam ve öneri ayara göre |
| Öneri kesinliği kanıttan yüksek | Doğru | Giderildi: profil eksikse "başlangıç noktası" notu; max_connections ≥ 500 ise bağlantı sayısı notu |

## Hasan'ın gözlemleri (aynı gün)

- "36 CPU × 0.5 = 4" yanlış hesap gibi okunuyordu: çarpım ve sınır ayrı gösteriliyor ("= 18 → üst sınır 4 = 4").
- Windows'ta patronictl komutları ve Patroni notu gösterilmiyor.
- Aynı zip'in ikinci kez import edilmesi kayıtları ikiledi: artık reddediliyor; yeni rapor için `health_check_report --health-check <id>`.

## Sonraki adımlar

1. Müşteriden yukarıdaki soruların cevabı; tablo doldurulur.
2. Yeni paketle tekrar toplama (index, vacuum, foreign key, extension) ve 172.30.207.13'teki replica'nın da toplanması.
3. Sunucu profili (iş yükü, PostgreSQL'e ayrılmış mı, disk tipi) girilerek önerilerin varsayımsız üretilmesi.

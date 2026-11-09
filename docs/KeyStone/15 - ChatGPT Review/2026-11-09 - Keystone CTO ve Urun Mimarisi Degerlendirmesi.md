# Keystone — CTO ve Ürün Mimarisi Değerlendirmesi

**9 Kasım 2026 · GitHub `main` ve 5 PostgreSQL Health Check raporu**

İlk olarak şunu söyleyeyim: **Keystone, Ekim ayında değerlendirdiğimiz ilk versiyona göre belirgin biçimde ilerlemiş.** Beni etkileyen yalnızca kontrol sayısındaki artış değil. Artık arkasında düşünülmüş bir mühendislik modeli, bu modeli uygulayan kodlar, mimari karar kayıtları ve farklı PostgreSQL ortamlarında üretilmiş sonuçlar var.

Ancak bu ilerleme yeni bir sorumluluk getiriyor: Keystone artık yalnızca sorun bulmuyor, **veritabanında hangi ayarların nasıl değiştirilmesi gerektiğini de öneriyor.** Bu nedenle yanlış tavsiyenin potansiyel maliyeti yükselmiş durumda.

Değerlendirmeyi üç seviyede yapıyorum: mevcut ürünün olgunluğu, düzeltilmesini istediğim teknik noktalar ve Keystone'un uzun vadeli yönü.

## 1. Ekim ayından bugüne ne değişmiş?

| | 19 Ekim 2026 | 9 Kasım 2026 |
|---|---|---|
| Değerlendirilen kontrol | **6** | **31** |
| Kapsam | Tek bir PostgreSQL cluster raporu, sınırlı sağlık değerlendirmesi | 10 assessment, 5 farklı lab ortamı, konfigürasyon mühendisliği |

**Repository'de bildirilen otomatik test sayısı: 353.**

31 kontrol, PostgreSQL MVP'nin güncel kapsamı; tek node ortamlarda uygulanabilir kontrol sayısı daha düşük.

GitHub'daki [Development Status](https://github.com/hasantatarli/keystone/blob/main/docs/DEVELOPMENT_STATUS.md) ve [MVP Plan](https://github.com/hasantatarli/keystone/blob/main/docs/KeyStone/02%20-%20Roadmap/MVP%20Plan.md) belgeleri de bu ilerlemeyi doğruluyor.

Özellikle şu gelişmeleri önemli buluyorum:

- Kontrollerin tek komutla çalıştırılması, zamanlanmış collection ve assessment altyapısı.
- `HEALTHY`, `ATTENTION_REQUIRED`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE` ve `ERROR` sonuçlarının ayrıştırılması.
- Tek node, primary-replica ve Patroni cluster senaryolarının desteklenmesi.
- PostgreSQL 15–18 sürümlerinin farklı davranışlarının dikkate alınması.
- Konfigürasyon önerilerinin ayrı, açıklanabilir bir hesaplama yeteneği olarak ele alınması.
- Kanıtların ve değerlendirme sonuçlarının merkezi repository'de saklanması.

En önemli mimari kazanım, bence hâlâ şu:

**Collector ne gözlemlendiğini kaydediyor; Engineering Intelligence ise bunun ne anlama geldiğine karar veriyor.**

Bu ayrım korunmuş. Keystone'un geleceği açısından çok değerli.

## 2. Beş raporun karşılaştırması

*9 Kasım 2026 tarihli HTML raporlarından çıkardığım sonuçlar*

| Sistem | Node | Kontrol sonucu | Uyarı | Eksik değerlendirme |
|---|---:|---:|---:|---:|
| pg-cluster, PG 17.10 | 3 | 30/31 | 4 | 1 |
| pg15-lab, PG 15.19 | 1 | 27/29 | 2 | 2 |
| pg16-lab, PG 16.15 | 1 | 27/29 | 2 | 2 |
| pg17-lab, PG 17.11 | 2 | 31/31 | 2 | 0 |
| pg18-lab, PG 18.6 | 1 | 27/29 | 2 | 2 |

*Uyarı sütunu WARNING sonuçlanan kural sayısını gösterir; aynı kural birden fazla node veya nesne için bulgu üretebilir. Standalone sistemlerde ayrıca 2 replikasyon kontrolü NOT_APPLICABLE.*

Bütün raporlarda WAL arşivlemesi ve SSL yapılandırmasıyla ilgili uyarılar var. Cluster raporunda bunlara yakın zamanda gerçekleşen failover ve PUBLIC schema yetkisi ekleniyor.

Daha önemlisi, PostgreSQL 15, 16 ve 18 raporlarında SSH üzerinden host bilgisi toplanamadığında Keystone bunu gizlemiyor:

- Disk kapasitesi değerlendirilemiyor.
- Bellek riskinin bir bölümü değerlendirilemiyor.
- Donanıma bağımlı 10 konfigürasyon önerisi hesaplanamıyor.

**Ekim ayında en çok eleştirdiğim yanlış güven verme probleminin önemli ölçüde düzeltildiğini görüyorum.**

Ayrıca standalone sunucularda replication lag kontrolünün HEALTHY değil, NOT_APPLICABLE olması doğru mühendislik davranışı.

Bu sadece rapor metni düzeltmesi değil, değerlendirme modelinin olgunlaştığının işareti.

## 3. Özellikle güçlü bulduğum mimari kararlar

### Deterministik intelligence'ın merkeze yerleşmesi

[ADR-0017 — Configuration Recommendations](https://github.com/hasantatarli/keystone/blob/main/docs/KeyStone/10%20-%20Decisions%20%28ADR%29/ADR-0017%20-%20Configuration%20Recommendations.md) belgesinde formüllerin Python kodunda, parametrelerin Dictionary'de tutulmasını doğru buluyorum.

Örneğin `shared_buffers` için yalnızca mevcut değeri okumuyorsunuz. Bellek, workload, dedicated/shared sunucu profili ve cluster'ın en küçük node'unu dikkate alıyorsunuz.

Bu, statik bir SQL health check script'inden daha gelişmiş bir yaklaşım.

Ayrıca her ayar sapmasının WARNING yapılmaması önemli. Çünkü bir DBA'nın bilinçli olarak seçtiği değer, Keystone'un varsayılan tavsiyesinden farklı diye problem sayılmamalı.

### Uygulanamaz ve değerlendirilemez durumlarının ayrılması

Bu konu ayrıca takdiri hak ediyor.

Örneğin PostgreSQL 18 standalone sunucuda replica bulunmaması başka, replica durumunu ölçememek başka şeydir.

Keystone'un bu iki durumu birbirinden ayırması, yalnızca raporun değil, ilerideki portfolio overview'un da doğruluğunu artıracak.

### Laboratuvar test stratejisi

Farklı PostgreSQL sürümleri, cluster topolojileri ve SSH erişiminin olduğu/olmadığı ortamları kullanmak doğru.

Ancak 353 testin varlığı ile üretim olgunluğu aynı şey değil. Henüz büyük veritabanları, gerçek workload ve müşteri erişim kısıtları altında yapılmış karşılaştırmalı doğrulama eksik. Bunun roadmap'te açıkça belirtilmiş olması iyi.

---

## 4. Düzeltilmesini istediğim teknik noktalar

Burada önceki değerlendirmeme göre daha seçici olacağım. Rapordaki her ifadeye müdahale etmek istemiyorum. Müşterinin yanlış karar vermesine yol açabilecek konulara odaklanıyorum.

### 4.1. Konfigürasyon önerilerinde varsayımlar yeterince belirleyici mi?

**Öncelikli inceleme**

Örneğin `pg17-lab` raporunda:

| Ayar | Mevcut | Önerilen |
|---|---:|---:|
| shared_buffers | 64 MB | 246 MB |
| effective_cache_size | 4 GB | 738 MB |
| checkpoint_timeout | 5 min | 15 min |
| wal_buffers | 2 MB | 16 MB |
| random_page_cost | 4 | 1.1 |
| effective_io_concurrency | 1 | 200 |

`shared_buffers` hesabı açık: 1.968 MB fiziksel bellek, sunucunun PostgreSQL'e ayrılmış olmadığı bilgisi ve %25 oranı kullanılmış.

Bu güzel.

Ama aynı raporda disk tipi SSD olarak *varsayılmış*. Bu nedenle `random_page_cost=1.1` öneriliyor.

Burada bir fark olmasını isterim:

- **Doğrulanmış öneri:** Gerekli donanım ve iş yükü bilgileri mevcut.
- **Varsayıma dayalı öneri:** Bazı girdiler bilinmiyor, varsayılan değerler kullanıldı.
- **Değerlendirilemedi:** Karar üretmek için zorunlu bilgi yok.

Her ayar için ayrı bir confidence yüzdesi üretmemizi istemiyorum. Mevcut `assumptions` alanı bu ayrımı göstermek için yeterli olabilir.

Özellikle kopyalanabilir SQL üretiyorsak varsayıma dayalı bir tavsiyeyi, kesin mühendislik kararı gibi sunmamalıyız.

### 4.2. Otomatik üretilen SQL komutları dikkat istiyor

Raporlarda şu yaklaşım var:

```sql
ALTER SYSTEM SET shared_buffers = '246MB';
ALTER SYSTEM SET effective_cache_size = '738MB';
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET wal_buffers = '16MB';

SELECT pg_reload_conf();
```

Ayrıca Patroni için `patronictl edit-config` komutları bulunuyor.

Bunları doğrudan uygulamıyor olmanız çok doğru.

Fakat konfigürasyon mühendisliği açısından şu ayrımları daha belirgin yapmak isterim:

**Birincisi:** `ALTER SYSTEM` ile değiştirilen `postmaster` context ayarları reload ile etkinleşmez. Raporda restart gerektiren ayarlar işaretleniyor; bu olumlu. Ancak komut bloğunun tamamını kopyalayan kullanıcı bütün değişikliklerin etkinleştiğini varsayabilir.

**İkincisi:** Patroni ile yönetilen cluster'larda DCS üzerinden yönetilen parametrelerle node'a özgü parametreler aynı şekilde ele alınamaz. Gösterilen komutların cluster yönetim biçimine uygunluğu doğrulanmalı.

**Üçüncüsü:** `wal_buffers`, `checkpoint_timeout`, `random_page_cost` gibi parametreler üzerinde yalnızca en iyi uygulama değerlerinden hareketle değişiklik yapmak her zaman doğru olmayabilir.

Örneğin `checkpoint_timeout=15min` genel bir tavsiye olabilir; fakat mevcut checkpoint sıklığı ve WAL üretimi değerlendirildiğinde değişikliğe gerek olmayabilir.

Keystone'un amacı herkesi aynı yapılandırmaya getirmek olmamalı.

**Amaç, hangi mevcut ayarın neden değiştirilmeye değer olduğunu göstermek olmalı.**

### 4.3. Bellek aşırı taahhüdü kuralı fazla kesin konuşmamalı

Kodda PG-CONF-007 için kullanılan yaklaşım:

`shared_buffers + max_connections × work_mem`

değerini fiziksel bellekle karşılaştırıyor.

Bu, potansiyel bellek riski açısından yararlı bir başlangıç göstergesidir.

Ancak PostgreSQL'de `work_mem` bağlantı başına sabit bir bellek tahsisi değildir. Bir sorgu birden fazla sort veya hash operasyonu yapabilir; paralel worker'lar da bellek kullanır. Tersine, birçok bağlantı hiç `work_mem` kullanmayabilir.

Dolayısıyla bu hesap hem yanlış pozitif hem yanlış negatif üretebilir.

Ben bu kuralı kaldırmazdım. Fakat sonuç metnini "bellek aşırı taahhüdü kesin olarak var" yerine, **"konfigürasyondan hesaplanan potansiyel bellek baskısı riski"** olarak değerlendirirdim.

CRITICAL kararı için daha fazla kanıt gerekebilir. Özellikle gerçek kullanılan bağlantı sayısı, workload ve bellek davranışı önemli.

### 4.4. WAL arşivleme ve yedekleme birbirine eşit değil

Beş raporun tamamında WAL arşivleme uyarısı var.

Bulgular doğru olabilir; `archive_mode=off` gözlemlenmiş.

Ama rapordaki bu tür ifadeleri dikkatli kullanmalıyız:

> Arşivleme kapalıysa veritabanı yalnızca son tam yedeğin alındığı ana döndürülebilir.

Bu her backup mimarisinde mutlak doğru değil. WAL'ın başka yöntemlerle korunması veya farklı bir yedekleme hizmeti kullanılması mümkün.

Ayrıca `archive_mode=off` olması, sistemde hiç yedek alınmadığı anlamına gelmiyor.

Benzer şekilde WAL arşivlemesinin açık ve çalışıyor olması da **restore edilebilir bir backup bulunduğunu veya RPO/RTO hedeflerinin karşılandığını ispatlamıyor.**

Bence gelecekte Keystone'un en değerli DBA yeteneklerinden biri backup ve recoverability assessment olacak.

Ancak MVP'de şu üç kavram ayrı kalmalı:

| Kontrol | Ne söyler? |
|---|---|
| WAL archiving | Arşivleme yapılandırması ve gözlemlenen çalışma durumu |
| Backup verification | Gerçek yedeklerin varlığı, güncelliği ve bütünlüğü |
| Restore readiness | Hedeflenen noktaya ve sürede geri dönüşün doğrulanması |

Bugün ilkini değerlendiriyoruz. Diğer ikisini sağlıklı göstermemeliyiz.

### 4.5. Failover zamanını hesaplama yöntemi

`pg-cluster` raporunda son failover zamanı 11:47:23, rapor anında yaklaşık 3 saat 21 dakika önce olarak gösteriliyor.

Kodda `PG_WAL_STATUS`, timeline history dosyasının modification time bilgisini topluyor.

Bu akıllıca bir dolaylı kanıt. Ancak history dosyasının modification time değeri, her durumda gerçek failover olayının güvenilir zaman damgası olmayabilir. Dosyanın kopyalanması veya restore edilmesi bu zamanı etkileyebilir.

Dolayısıyla:

- Yeni timeline: güçlü bir geçmiş olay göstergesi.
- History dosyasının modification time değeri: tahmini zaman bilgisi.
- Planlı switchover mı, beklenmedik failover mı: mevcut kanıtlarla kesin belirlenemiyor.

Bu bulgunun açıklamasında **gözlemlenen timeline değişimi ile olayın kesin nedeni/zamanı** birbirinden ayrılmalı.

Bu arada cluster'ın timeline değerinin 145 olması, geçmişinde çok sayıda timeline değişimi yaşandığına işaret ediyor. Böyle bir ortamda yöneticinin asıl sorusu "Neden bu kadar sık?" olacaktır. Bu soru gelecekteki Change & History Explorer için çok iyi bir kullanım senaryosu.

## 5. Raporlarda hâlâ gördüğüm küçük ama önemli sorunlar

Bunların hepsini hemen geliştirme listesine almam.

| Gözlem | Değerlendirmem |
|---|---|
| SSH eksikliğinde kapasite alanı "Sorun bulunmadı" gösterebiliyor | Etkilenen alanlar özetinde eksik kanıt daha görünür olmalı |
| pg15/16/18'de "2 kontrol yapılamadı", detay kartında "3" yazıyor | İki kural ile bir kısmi konfigürasyon değerlendirmesi sayılıyor; sayıların anlamı açıklanmalı |
| `ssl=off` için "tüm bağlantılar açık metin" deniyor | PostgreSQL'in doğrudan TLS kabul etmediği kesin; bütün uçtan uca bağlantıların açık metin olduğu değil |
| Timeline 1 için "Hiç failover olmamış" deniyor | Daha dar ifade: "Mevcut WAL geçmişinde timeline değişimi gözlenmedi" |
| Sequence SELECT yetkisi eksik | Güvenlik ilkesi gereği tüm sequence'lere toplu GRANT vermek yerine gerektiği kadar dar yetki önerilmeli |

Özellikle SSH eksikliği ile "Kapasite: Sorun bulunmadı" ifadesi arasında hâlâ bir sunum gerilimi var.

Alanlara göre durum bölümünde "Kısmen değerlendirildi" yazmanız doğru. Ama yönetici, yalnızca etkilenen alanlar bölümüne bakarsa bu eksikliği görmeyebilir.

Ekim'de konuştuğumuz **kanıt yoksa sağlıklı kabul etme** ilkesini bütün özet seviyelerinde tutarlı uygulamalıyız.

---

## 6. Keystone'un mimarisinde gördüğüm en önemli fırsat

Burada önceki görüşmemizdeki 50 sunucu konusuna dönmek istiyorum.

GitHub dokümantasyonunda bu konunun unutulmadığını gördüm.

[Reference Architecture](https://github.com/hasantatarli/keystone/blob/main/docs/KeyStone/04%20-%20Architecture/Reference%20Architecture.md) şu dört sunum seviyesini tanımlıyor:

1. **Estate Overview** — Bütün yönetilen PostgreSQL sistemlerinin genel mühendislik durumu.
2. **System Engineering View** — Bir cluster veya standalone instance'ın durumu.
3. **Finding / Investigation Workspace** — Kanıt, olası kök neden ve önerilerle inceleme.
4. **Change & History Explorer** — Zaman içindeki değişim, eğilim ve değerlendirme geçmişi.

Bu modeli destekliyorum.

Özellikle **Estate Overview'un bağımsız bir intelligence motoru olmaması**, önceki değerlendirmemizle uyumlu.

Ancak bir noktayı eklemek istiyorum: Overview, yalnızca son raporlardaki CRITICAL ve WARNING sayılarını toplamakla sınırlı kalmamalı.

Örneğin 50 sunuculuk bir ortamda şu üç senaryo birbirinden ayrılmalı:

- 5 target CRITICAL.
- 5 target değerlendirilemiyor.
- 5 target'ın son değerlendirmesi üç gün önce yapılmış.

Bunların her biri operasyonel dikkat gerektirir; fakat aynı anlama gelmez.

Keystone'u değerli kılacak şey yalnızca kaç sorun olduğunu söylemesi değil, **hangi sistemin mühendislik durumuna güvenebileceğimizi de göstermesi**.

## 7. Bence gelecekteki asıl farklılaştırıcı: Engineering Investigation

Burası benim ürün vizyonunda en çok önemsediğim alan.

Zabbix, Prometheus ve Grafana gibi araçlar bize sistemde ne olduğunu gösterebilir. Keystone'un hedefi bunlarla aynı ekranları üretmek olmamalı.

Keystone bir adım daha ileri gitmeli.

Örneğin PostgreSQL'de replication lag yükseldiğini düşünelim.

Basit monitoring bize gecikmenin 120 saniye olduğunu gösterir.

Keystone'un Engineering Intelligence katmanı ise zamanla şu kanıtları bir araya getirebilmeli:

### Örnek: Replication Lag Investigation

**Gözlem: Replica gecikmesi yükseldi**

*Örnek değer: 120 saniye.*

| Destekleyen kanıtlar | Eksik kanıtlar |
|---|---|
| Replay LSN ilerlemiyor, WAL receive devam ediyor | Disk I/O gecikmesi, replica wait events |

**Olası neden: Replay darboğazı**

*Kesin kök neden değil; yeni kanıtlarla doğrulanması gereken hipotez.*

**Önerilen sonraki inceleme:** Replica üzerindeki replay durumu ve I/O beklemelerini karşılaştır.

*Bu bir gelecek vizyonu örneğidir; mevcut Keystone'un bu RCA analizini yaptığı iddiası değildir.*

Bu seviyeye ulaşırsak Keystone'u yalnızca health check ürünü olarak pazarlamak zorunda kalmayız.

**Veritabanı mühendisinin karar verme sürecini hızlandıran bir platform** haline gelir.

Ve burada AI'ın doğru konumu da ortaya çıkıyor: Yapay zekâ gözlemleri açıklayabilir, hipotezleri karşılaştırabilir ve eksik kanıtları önerebilir. Ama doğrulanmamış bir hipotezi kesin kök neden olarak sunmamalı.

Bununla birlikte, bu kapasiteyi şimdi geliştirmeye başlamamızı önermiyorum. Mevcut assessment ve evidence temelini gerçek bir müşteri ortamında doğrulamak daha değerli.

## 8. Bundan sonra neye öncelik verirdim?

MVP Plan'da sıradaki adaylar arasında P2 kurallar ve offline evidence bundle var.

Ben burada biraz farklı önceliklendirirdim.

| Sıra | Çalışma | Kararım |
|---|---|---|
| 1 | Gerçek müşteri ortamında manuel DBA değerlendirmesiyle karşılaştırma | **En yüksek öncelik** |
| 2 | Konfigürasyon önerilerinin ve üretilen komutların güvenilirliğinin doğrulanması | En yüksek öncelik |
| 3 | Offline evidence bundle | MVP için gerekli |
| 4 | İlk müşteri raporunun teslim deneyimi | MVP için gerekli |
| 5 | Estate Overview — basit HTML | Çoklu target için önemli |
| 6 | Mevcut kanıtları kullanan yeni P2 kurallar | Seçerek devam |
| 7 | Finding lifecycle, tarihsel analiz, RCA | Sonraki aşama |

Burada özellikle ilk maddeyi savunuyorum.

Şimdiye kadar lab üzerinde çok sayıda senaryo doğrulanmış. Bu iyi. Ama Keystone'un ürettiği sonuçları gerçek bir PostgreSQL ortamında, deneyimli bir DBA'nın manuel incelemesiyle karşılaştırmak ürünün eksiklerini başka türlü göremeyeceğimiz kadar net gösterebilir.

Örneğin 200 GB veri, farklı tablespace'ler, büyük transaction tabloları, özel autovacuum ayarları ve gerçek yedekleme politikası olan bir müşteri sisteminde Keystone ne söylüyor?

Manuel inceleme ile farklar neler?

Bence bu çalışma, on yeni kural yazmaktan daha fazla değer üretebilir.

## 9. Claude'a özellikle sormak istediğim mimari sorular

Kodun bir bölümünü ve dokümantasyonu inceledim. Aşağıdaki konuları Claude ile tartışmaya değer buluyorum.

### Soru 1 — Eksik node kanıtıyla cluster önerisi üretimi

`config_recommendations.py` içindeki `server_facts()` fonksiyonunda bellek ve CPU için mevcut host verilerinin minimumu alınıyor.

Bir cluster'da üç node varsa, ancak yalnızca ikisinin SSH verisi başarılıysa, en küçük node'un gözden kaçması mümkün.

Bu durumda Keystone öneri hesaplamaya devam mı ediyor, yoksa eksik node bilgisi nedeniyle değerlendirmeyi kısıtlıyor mu? Bence bu kritik.

### Soru 2 — Konfigürasyon tavsiyesinin güven düzeyi

Varsayılan SSD, workload ve dedicated bilgisiyle hesaplanan önerilerle, doğrulanmış profilden hesaplanan öneriler aynı şekilde mi sunulmalı?

`assumptions` mevcut. Bunun rapordaki görünürlüğü yeterli mi?

### Soru 3 — SQL/Patroni komutlarının üretim güvenliği

`ALTER SYSTEM`, reload, restart ve Patroni DCS parametrelerinin doğru kullanımını test eden senaryolar ne kadar kapsamlı?

Mevcut testler komut formatını mı doğruluyor, yoksa gerçek PostgreSQL/Patroni ortamında uygulanabilirliğini de doğruluyor mu?

### Soru 4 — Estate Overview'un veri modeli

ADR-0016 henüz tamamlanmamış görünüyor. Overview mevcut `health_check`, `assessment_result` ve `finding` verileriyle üretilebilir mi?

Customer kavramı dışında yeni bir kalıcı veri modeli gerçekten gerekli mi?

### Soru 5 — Gerçek müşteri pilotu

Laboratuvar testlerinden sonra gerçek müşteri sistemine geçmek için en büyük teknik engel nedir?

Offline bundle mı, yetkilendirme mi, collector performansı mı, yoksa sonuçların doğruluğuna ilişkin eksik testler mi?

Bunlara Claude'un cevaplarını merak ediyorum. Özellikle ilk üç soruyu kod seviyesinde ele almak isterim.

---

## 10. Genel CTO değerlendirmem

| Alan | Değerlendirme |
|---|---:|
| Mimari yön | **9/10** |
| MVP işlevselliği | **8/10** |
| Raporlama | **8.5/10** |
| Üretim güvenilirliği | **6/10** |

*Öznel ürün değerlendirmesi; kapsamlı güvenlik denetimi, yük testi veya canlı müşteri validasyonu yerine geçmez.*

Önceki incelemede teknik güvenilirlik için 5.5/10 vermiştim. Bugün mimarinin ve raporlama doğruluğunun geliştiğini görüyorum.

Ama üretim güvenilirliğine henüz yüksek puan vermememin nedeni net: Gerçek sistemde uzun süreli çalışma, yetki kısıtları, büyük veri hacimleri ve önerilerin etkisi henüz yeterince doğrulanmamış.

### Bir de ürünün gelişim süreciyle ilgili gözlemim var

Development Status'ta son konfigürasyon önerisi çalışmasının altı PR ve çok sayıda düzenleme turu aldığı belirtilmiş.

Bu bence üzerinde düşünmeye değer.

Keystone için en büyük tehlikelerden biri, çok sayıda mühendislik özelliği eklerken gerçek müşteri doğrulamasını sürekli ertelemek olabilir.

Bu aşamada yeni özellik sayısından çok şu sorunun cevabına odaklanırdım:

**"Keystone'un bugünkü çıktısını gerçek bir müşteriye verdiğimizde, müşteri hangi mühendislik kararlarını daha hızlı, doğru ve güvenilir verebiliyor?"**

Bu soruya güçlü bir cevap verebildiğimizde ticari ürünün temeli ortaya çıkacak.

## Sonuç

Keystone'un yönünü değiştirmeyi önermiyorum. Mevcut mimariyi atıp yeni bir çerçeve kurmak da gereksiz.

Benim önerim, artık **özellik geliştirme odaklı aşamadan kontrollü ürün doğrulama aşamasına** geçmemiz.

Bu arada Estate Overview, Finding Lifecycle, RCA ve AI Engineering Assistant vizyonlarını koruyalım; fakat hepsini aynı anda gerçekleştirmeye çalışmayalım.

Keystone'un en güçlü vaadi bence şu cümleyle ifade edilebilir:

> **Keystone, veritabanlarının yalnızca ne durumda olduğunu değil, hangi mühendislik risklerinin bulunduğunu, bunların hangi kanıtlara dayandığını ve hangi aksiyonların değerlendirilmesi gerektiğini gösterir.**

Bu, baştan beri konuştuğumuz ürün vizyonuyla uyumlu.

Claude ile ilk tartışmak istediğim konu ise yeni P2 kontrolleri değil, **konfigürasyon önerilerinin güvenilirliği ve ilk gerçek müşteri validasyonunun nasıl yapılacağı**. Çünkü bunlar çözüldüğünde Keystone yalnızca etkileyici raporlar üreten bir proje olmaktan çıkıp güvenilir bir DBA mühendislik aracına dönüşmeye başlayacak.

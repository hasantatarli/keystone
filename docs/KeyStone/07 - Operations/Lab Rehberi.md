# Lab Rehberi

Lab'da sık çalıştırdığımız komutlar: her biri ne yapar, Keystone'un hangi parçasına dokunur, ne zaman gerekir. Bütün seçenekler [[Command Reference]]'ta; bu sayfa günlük akış için.

Komutlar repository kökünden çalışır (`C:\Yazılım\keystone`). PowerShell'de komutlar ayrı satırlarda verilir; `&&` kullanılmaz.

---

## Keystone'un parçaları (komutların neye dokunduğu)

| Parça | Ne | Nerede |
|---|---|---|
| Repository | Keystone'un kendi PostgreSQL veritabanı (`keystone_lab`): hedefler, toplanan kanıt, kurallar, sonuçlar | `keystone` şeması |
| Dictionary | Kurallar, eşikler, metinler (tr/en). Yalnızca migration ile değişir | `rule_definition`, `rule_threshold`, `rule_text`… |
| Migration | Repository'ye şema ve Dictionary değişikliği getiren SQL dosyaları (V001…V059, PG001…PG023) | `repository/migrations`, `providers/.../migrations` |
| Collector | Hedef sunucudan kanıt toplayan salt-okunur SQL ya da host betiği | `providers/postgresql/telemetry/collectors` |
| Assessment engine | Kanıtı kurallara göre değerlendirir: Sağlıklı, Uyarı, Kritik, Değerlendirilemedi | `repository/intelligence` |
| Health check | Bir hedef için: topla → değerlendir → rapor | `repository/healthcheck` |
| Offline paket | Keystone'un bağlanamadığı müşteride çalışan toplama betikleri ve import | `repository/offline` |
| Sürüm referansı | PostgreSQL sürümleri ve destek tarihleri (ADR-0019) | `release_reference` |

---

## 1. Ortam

Her komut repository bağlantısını ve anahtarı ortam değişkenlerinden okur (`KEYSTONE_REPOSITORY_*`, `KEYSTONE_MASTER_KEY`). Yeni bir PowerShell penceresinde bunlar yoksa komutlar bağlanamaz.

- Ayarlamak: `$env:AD = "değer"` (`set AD=değer` PowerShell'de çalışmaz).
- **Master key ve parolalar ekrana, dokümana ya da sohbete yazılmaz.**

---

## 2. Bir PR'ı lab'da doğrulama

Akış: branch → testler → draft PR → **lab doğrulaması (sen)** → ready → merge (sen).

```powershell
git fetch
git checkout <branch>
git pull
python -m repository.install.install
python -m repository.healthcheck.health_check --target 1 --report tr
```

| Komut | Ne yapar |
|---|---|
| `git fetch` | GitHub'daki yeni branch'leri ve commit'leri indirir; çalışma klasörünü değiştirmez |
| `git checkout <branch>` | Klasörü o branch'in koduna geçirir |
| `git pull` | Branch'in en son halini çeker (GitHub'da yeni commit varsa) |
| `install` | Bekleyen migration'ları uygular ve collector'ları kaydeder. Çıktıda `Pending migrations : 1` görürsün; ikinci kez çalıştırırsan `0` der — bu hata değil, zaten uygulanmış demektir |
| `health_check --target 1 --report tr` | Hedef 1 için (lab'daki Patroni cluster, SYSTEM; bütün node'ları kapsar) kanıt toplar, bütün assessment'ları çalıştırır, Türkçe HTML raporu yazar. Çıktıda health check numarası (hcNNN) ve rapor dosyası yazar |

Rapora bakarken: beklenen bulgular çıkmış mı, metinler doğru mu, "değerlendirilemedi" olanların sebebi anlaşılır mı.

## 3. Merge sonrası

```powershell
git checkout main
git pull
```

Main'e geçer ve merge edilen kodu çeker. Migration lab doğrulamasında zaten uygulandıysa install gerekmez.

---

## 4. Var olan bir health check'in raporunu yeniden üretmek

```powershell
python -m repository.report.health_check_report --health-check 111 --lang tr
```

Kanıtı ve sonuçları değiştirmez; yalnızca raporu güncel rapor koduyla yeniden yazar (rapor görünümü değiştiğinde). **Yeni kurallar eski health check'e eklenmez**: yeni bir kural için yeni toplama ya da health check gerekir.

---

## 5. Offline (müşteri) toplama

```powershell
python -m repository.offline.bundle --out C:\keystone-offline
```

Müşteriye gidecek betikleri collector dosyalarından üretir (elle düzenlenmez). İçindeki `KILAVUZ_TOPLAMA.md` müşteri için adımları anlatır. Collector değiştiyse paket yeniden üretilmeli; eski paketle toplanan kanıt import'ta reddedilir.

Müşteri tarafı (tek çalıştırma; bütün sunucular, bütün veritabanları, host bilgisi):

```powershell
powershell -ExecutionPolicy Bypass -File keystone_collect.ps1
```

Gelen zip'i içeri almak:

```powershell
python -m repository.offline.import_bundle keystone_evidence_<tarih>.zip --name "Musteri DB" --environment PROD --report tr
```

Kanıtı repository'ye yazar, toplandığı zamana göre değerlendirir ve raporu üretir. **Aynı zip ikinci kez reddedilir**; o check'in raporu için 4. bölüm.

---

## 6. Sürüm referansı

```powershell
python -m repository.lifecycle.release_reference --show
python -m repository.lifecycle.release_reference --refresh
```

`--show` listeyi, kaynağını (SEED kurulumla gelen, FILE dosya, ONLINE internet) ve tarihini gösterir. `--refresh` internetten yeniler; health check ve import bunu kendileri de dener. İnterneti olmayan Keystone için: interneti olanda `--export dosya.json`, olmayanda `--import dosya.json`. Liste 100 günden eskiyse minor sürüm kontrolü "değerlendirilemedi" der.

---

## 7. Kontrol sorguları

```sql
-- hedefler (SYSTEM = cluster, NODE = sunucu)
SELECT target_id, name, target_type, parent_target_id FROM keystone.target ORDER BY target_id;

-- bir migration uygulanmış mı
SELECT component, version, status, executed_at FROM keystone.migration_history ORDER BY execution_id DESC LIMIT 5;

-- son health check'ler
SELECT health_check_id, target_id, started_at, status, status_message
FROM keystone.health_check ORDER BY health_check_id DESC LIMIT 5;
```

Daha fazlası (collector çalışmaları, kural sonuçları, olay kaydı): [[Command Reference]] bölüm 10.

---

## Sık karşılaşılanlar

| Gördüğün | Anlamı |
|---|---|
| install: `Pending migrations : 0` | Migration'lar zaten uygulanmış; sorun değil |
| import: "already imported as health check N" | Aynı kanıt iki kez alınmaz; raporu 4. bölümle üret |
| import: collector changed / FAILED | Paket eski; 5. bölümle yeniden üret, müşteri yeniden toplasın |
| Kural "Değerlendirilemedi" | Gerekli kanıt yok ya da eski; raporda sebebi ve çoğu zaman ne yapılacağı yazar |
| PowerShell'de `&&` hatası | Komutları ayrı satırlarda çalıştır |

# Keystone offline kanıt toplama kılavuzu

Bu klasördeki script'ler, Keystone'un PostgreSQL sağlık kontrolü için gereken bilgileri **Keystone'u kurmadan ve sisteme bağlamadan** toplar. Çıkan dosyalar daha sonra Keystone'a aktarılır ve rapor oradan üretilir.

## Güvence

- Script'ler yalnızca **okur**: sistem kataloglarına ve istatistik görünümlerine tek bir `SELECT` çalışır. Hiçbir nesne oluşturmaz, hiçbir ayarı değiştirmez, hiçbir şey kurmaz.
- **Toplanmayanlar:** tablolardaki veriler, sorgu metinleri, şifreler.
- **Toplananlar:** PostgreSQL ayarları, veritabanı ve tablo adları ile boyutları, bakım ve istatistik sayaçları, oturum durumları (sorgu metni olmadan), replikasyon durumu, rol adları ve yetkileri, index kullanımı. Ne toplandığını SQL dosyalarının içinde görebilirsiniz.
- Gereken yetki: superuser ya da `pg_monitor` rolü yeterlidir.

## En kolay yol: toplayıcı script (önerilen)

Tek bir script sunucuya bağlanır, **bütün veritabanlarını kendisi bulup dolaşır** ve her şeyi tek bir arşiv dosyasında toplar. Veritabanı sayısı ne olursa olsun bir kez çalıştırmak yeter.

Gereken tek şey `psql`. Windows'ta pgAdmin kurulumunun içinde gelir (`pgAdmin 4\runtime\psql.exe`); script onu ve PostgreSQL kurulum klasörünü kendisi arar. Linux'ta PostgreSQL sunucusunda zaten vardır.

**Windows** (PowerShell):

```
powershell -ExecutionPolicy Bypass -File keystone_collect.ps1
```

**Linux:**

```
sh keystone_collect.sh
```

Script şunları sorar:

| Soru | Açıklama |
|---|---|
| Sunucu(lar) | Adres ya da ad. Birden fazla sunucu virgülle (örn. Patroni node'ları: `db-1,db-2,db-3`). Linux'ta sunucunun kendisinde `local` yerel bağlantı kullanır. |
| Port | Varsayılan 5432 |
| Kullanıcı | Superuser ya da `pg_monitor` rolü olan bir kullanıcı |
| Şifre | Ekranda görünmez, hiçbir yere kaydedilmez, iş bitince bellekten silinir |
| Çıktı klasörü | Varsayılanı script'in yanında yeni bir klasör |
| Keystone'daki sunucu adı | Her sunucu için; dosyalar bu adla adlandırılır. Size verilen adı yazın. |
| Bu makine mi? | Script veritabanı sunucusunun kendisinde çalışıyorsa "e": bellek, CPU ve disk bilgisi de toplanır |

Sonunda tek bir dosya oluşur: Windows'ta `.zip`, Linux'ta `.tar.gz`. **Gönderilecek dosya budur.**

Script'leri aynı anda, birbirine yakın zamanda çalıştırın (ideal olarak 10 dakika içinde); oturum ve replikasyon bilgileri kısa ömürlüdür.

## psql yoksa: pgAdmin ile elle (yedek yol)

| Dosya | Nerede çalışır | Kaç kez |
|---|---|---|
| `keystone_node.sql` | Her sunucuda, `postgres` veritabanında | Sunucu başına 1 |
| `keystone_database.sql` | Her sunucuda, **her veritabanında** (`postgres` dahil) | Sunucu × veritabanı |

1. Veritabanında **Query Tool**'u açın, script'i açıp çalıştırın (F5).
2. Sonuç tek hücredir (`keystone_evidence`). Sonuç alanındaki "Save results to file" ile kaydedin ya da hücreyi kopyalayıp bir metin dosyasına yapıştırın.
3. Dosyaları sunucu ve veritabanı adıyla adlandırın: `<sunucu>_node.json`, `<sunucu>_db_<veritabanı>.json`.

## Sunucu bilgisi (isteğe bağlı)

Bellek, CPU ve disk bilgisi olmadan konfigürasyon önerilerinin bir kısmı ve disk doluluğu kontrolü yapılamaz; rapor bunu "değerlendirilemedi" olarak gösterir.

**Linux** (sistem yöneticisi, normal kullanıcı yeterli):

```
sh host_snapshot.sh > postgre-1_host.txt
```

**Windows** (PowerShell):

```
powershell -ExecutionPolicy Bypass -File host_snapshot_windows.ps1 > DBSRV01_host.txt
```

Toplayıcı script "bu makine" denildiğinde bunu kendisi yapar. Ayrıca çalıştırmak isterseniz bu script'ler de yalnızca okur (Linux'ta `/proc`, `df`, `lsblk`; Windows'ta `Get-CimInstance`, `Get-Partition`, `Get-PhysicalDisk`).

Script çalıştırılamıyorsa her sunucu için şu bilgiler yeterlidir: bellek (GB), CPU çekirdek sayısı, veri diskinin boyutu ve doluluğu, disk tipi (SSD/HDD).

## Gönderim

Bütün dosyaları tek bir klasörde toplayıp iletin. Dosyalar düz metindir; göndermeden önce açıp içeriğini inceleyebilirsiniz.

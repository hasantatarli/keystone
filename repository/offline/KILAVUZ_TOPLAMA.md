# Keystone offline kanıt toplama kılavuzu

Bu klasördeki script'ler, Keystone'un PostgreSQL sağlık kontrolü için gereken bilgileri **Keystone'u kurmadan ve sisteme bağlamadan** toplar. Çıkan dosyalar daha sonra Keystone'a aktarılır ve rapor oradan üretilir.

## Güvence

- Script'ler yalnızca **okur**: sistem kataloglarına ve istatistik görünümlerine tek bir `SELECT` çalışır. Hiçbir nesne oluşturmaz, hiçbir ayarı değiştirmez, hiçbir şey kurmaz.
- **Toplanmayanlar:** tablolardaki veriler, sorgu metinleri, şifreler.
- **Toplananlar:** PostgreSQL ayarları, veritabanı ve tablo adları ile boyutları, bakım ve istatistik sayaçları, oturum durumları (sorgu metni olmadan), replikasyon durumu, rol adları ve yetkileri, index kullanımı. Ne toplandığını SQL dosyalarının içinde görebilirsiniz.
- Gereken yetki: superuser ya da `pg_monitor` rolü yeterlidir.

## Dosyalar

| Dosya | Nerede çalışır | Kaç kez |
|---|---|---|
| `keystone_node.sql` | Her sunucuda, `postgres` veritabanında | Sunucu başına 1 |
| `keystone_database.sql` | Her sunucuda, **her veritabanında** (`postgres` dahil) | Sunucu × veritabanı |
| `host_snapshot.sh` | Linux sunucuda, işletim sistemi kabuğunda (isteğe bağlı) | Sunucu başına 1 |
| `host_snapshot_windows.ps1` | Windows sunucuda, PowerShell'de (isteğe bağlı) | Sunucu başına 1 |

Örnek: 3 veritabanlı tek bir sunucu → 1 node + 4 veritabanı (`postgres` dahil) = 5 çalıştırma. Patroni cluster'ında her node için aynısı yapılır.

Script'leri **aynı oturumda, birbirine yakın zamanda** (ideal olarak 10 dakika içinde) çalıştırın; oturum ve replikasyon bilgileri kısa ömürlüdür.

## pgAdmin ile

1. Sunucuda `postgres` veritabanını seçip **Query Tool**'u açın.
2. `keystone_node.sql` dosyasını açın (Open File) ya da içeriğini yapıştırın ve çalıştırın (F5).
3. Sonuç tek satır, tek hücredir (`keystone_evidence`). İki yoldan biriyle alın:
   - **Kopyala:** Hücreyi seçip kopyalayın, bir metin dosyasına yapıştırın.
   - **Dosyaya kaydet:** Sonuç alanındaki "Save results to file" düğmesiyle CSV olarak kaydedin. Kopyalanan metin kesik görünüyorsa bu yolu kullanın.
4. Aynı işlemi `keystone_database.sql` ile **her veritabanında** tekrarlayın (Query Tool'u o veritabanında açarak).

## Dosya adları

Dosyaları sunucu ve veritabanı adıyla adlandırın; Keystone dosyanın hangi sunucudan geldiğini adından anlar:

```
<sunucu>_node.json
<sunucu>_<veritabanı>.json
<sunucu>_host.txt
```

Örnek: `postgre-1_node.json`, `postgre-1_postgres.json`, `postgre-1_app.json`, `postgre-1_host.txt`. CSV olarak kaydedilen dosyaların uzantısı `.csv` kalabilir.

## psql ile (varsa)

```
psql -h <sunucu> -d postgres -At -f keystone_node.sql -o postgre-1_node.json
psql -h <sunucu> -d app      -At -f keystone_database.sql -o postgre-1_app.json
```

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

Bu script'ler de yalnızca okur (Linux'ta `/proc`, `df`, `lsblk`; Windows'ta `Get-CimInstance`, `Get-Partition`, `Get-PhysicalDisk`).

Script çalıştırılamıyorsa her sunucu için şu bilgiler yeterlidir: bellek (GB), CPU çekirdek sayısı, veri diskinin boyutu ve doluluğu, disk tipi (SSD/HDD).

## Gönderim

Bütün dosyaları tek bir klasörde toplayıp iletin. Dosyalar düz metindir; göndermeden önce açıp içeriğini inceleyebilirsiniz.

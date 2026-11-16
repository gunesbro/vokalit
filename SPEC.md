# SPEC — Vokalit

Lokal ses klonlama ve seslendirme karşılaştırma aracı.

> Durum: **v1.7** (v1.6'ya göre: kendi kırpma aracımız denendi, geri alındı; Gradio'nun yerleşik kırpma aracı kullanılır — §7).
> Değişiklikler bu dosyada yapılır, sonra koda yansıtılır.

## 1. Amaç

Kullanıcının kendi bilgisayarında, ses/metin dışarı gönderilmeden, kısa bir referans kayıttan
(≥10 sn) Türkçe metni o sesle okutmak ve iki açık kaynak modelin sonucunu yan yana dinlemek.
Her şey masaüstü penceresinden tıklanarak yapılır.

## 2. Kapsam (v1)

- İki model: **Chatterbox Multilingual** (Resemble AI) ve **OmniVoice** (k2-fsa).
- Masaüstü penceresi (Gradio arayüzü + pywebview penceresi):
  - Referans sesi dosyadan yükleme veya mikrofondan kaydetme; kayıtta mikrofon seçimi, üretimden önce kaydı dinleme ve kırpma (Gradio'nun yerleşik aracı).
  - Okunacak metni girme.
  - İki ses modu:
    - **Clone voice:** referans sesle klonlayarak okutma.
    - **Default voice:** referans ses olmadan, modelin kendi sesiyle okutma.
  - Modeli kurma / kaldırma (kurulum öncesi boyut + onay).
  - Her modelin sonucunu oynatıcıda dinleme ve `.wav` olarak kaydetme.
- Donanım: **NVIDIA GPU (CUDA)**. İşletim sistemi: Windows 10/11 ve Linux.
- Lisans: **Unlicense** (kamu malı; telif sahibi yok). Yalnızca bu reponun kodunu kapsar; modellerin ve kütüphanelerin kendi lisansları geçerlidir.

## 3. Kapsam dışı (v1)

- Otomatik kalite ölçümleri (ses benzerliği, WER, RTF).
- CPU ve Apple Silicon desteği (GPU yoksa açık bir hata mesajı gösterilir).
- Komut satırı arayüzü (v0.2'deki `manage.py` / `compare.py` kaldırıldı; tüm işlemler pencereden).
- Tek tıkla yükleyici (.exe/.dmg), Docker.
- Fine-tuning, streaming üretim, üçüncü model, bulut API'leri.
- Disk alanı ön kontrolü, yarım indirmeyi sürdürme, otomatik güncelleme.

## 4. Seçilen modeller

| | Chatterbox Multilingual | OmniVoice |
|---|---|---|
| Türkçe | Var (`language_id="tr"`) | Var (600+ dil) |
| Boyut | ~500M parametre | ~0.6B parametre |
| Model indirme | ~2 GB | doğrulanmadı (~1.2 GB tahmini) |
| VRAM | ~3.5–4 GB | ~8 GB yeterli (RTX 4090 testi) |
| Referans | Ses dosyası | Ses dosyası + opsiyonel transkript (boşsa Whisper ile otomatik; Whisper kurulumda iner, bkz. §5.3) |
| Kod lisansı | MIT | Apache 2.0 |
| **Ağırlık lisansı** | MIT | **CC-BY-NC (ticari kullanım yok)** |
| Referanssız okuma | Var: `audio_prompt_path` verilmezse yerleşik varsayılan ses | Var: "Auto Voice" modu (`ref_audio` verilmez) |
| Not | Çıktılara PerTh filigranı ekler | |

**Doğrulanacak (plan adım 3/4):** Chatterbox'ın varsayılan sesinin Türkçede aksanlı olup
olmadığı; OmniVoice'un Auto Voice modunda her üretimde farklı bir ses seçip seçmediği.
Sonuç README'ye not edilir. OmniVoice'un sesi metinle tarif etme özelliği ("Voice Design")
v1 kapsamı dışında.

Lisans farkı kurulum onay penceresinde ve README'de gösterilir.

## 5. Mimari

```
┌──────────────────────────────┐
│  Uygulama (.local/app/venv)  │  Gradio + pywebview
└──────┬───────────────┬───────┘
       │ JSON satırları (stdin/stdout)
┌──────▼──────┐ ┌──────▼──────┐
│ Chatterbox  │ │ OmniVoice   │   her biri kendi venv'inde
│ işçisi      │ │ işçisi      │   model bir kez yüklenir, açık kalır
└─────────────┘ └─────────────┘
```

### 5.1 Ayrı ortamlar

Her model kendi venv'inde çalışır (torch/transformers sürüm çakışma riski). Uygulama
arayüzü de ayrı bir venv'dedir ve torch içermez.

### 5.2 İşçi protokolü

Uygulama, kurulu her model için bir işçi süreci başlatır (ilk "Üret"te, tembel). İşçi modeli
bir kez yükler, sonra stdin'den satır satır JSON okur, stdout'a satır satır JSON yazar.
Log/progress çıktıları stderr'e gider.

```
→ {"ref": "<yol>", "text": "...", "out": "<yol>", "ref_text": "..."}   # ref ve ref_text opsiyonel; ref yoksa varsayılan ses
← {"ok": true, "out": "<yol>", "seconds": 2.1}
← {"ok": false, "error": "mesaj"}
```

- Açılışta işçi bir kez `{"ready": true}` yazar (model yüklendi).
- Ağ portu açılmaz. Uygulama kapanınca işçiler sonlandırılır.

### 5.3 Gizlilik ve şeffaflık

**Temel kural:** Kullanıcının sesi, metni ve üretilen sesler hiçbir koşulda bilgisayardan çıkmaz.
Ağ yalnızca kullanıcı "Install" düğmesine basıp onay verdiğinde, paket ve model indirmek için kullanılır.

**Uygulama süreci (arayüz):**

- Gradio yalnızca `127.0.0.1`'e bağlanır, `share=False`.
- `GRADIO_ANALYTICS_ENABLED=False`, `HF_HUB_DISABLE_TELEMETRY=1`.
- Gradio bileşenlerinde "share" düğmesi kapalıdır (sesi Hugging Face'e yükler).
- Tema yazı tipleri sistem fontlarıdır (Gradio'nun varsayılan temasının Google Fonts'tan font çekmesi engellenir).
- Gradio'nun geçici dosyaları (yüklenen/kaydedilen sesler) `GRADIO_TEMP_DIR=.local/tmp` altına yazılır,
  uygulama kapanırken silinir. Sistem geçici klasörüne ses bırakılmaz.

**İşçi süreçleri (sesi işleyen yer) — teknik olarak zorunlu:**

- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`: kütüphaneler ağa çıkmaya çalışmaz.
- İşçi, herhangi bir kütüphaneyi import etmeden önce soket oluşturmayı engeller
  (`socket.socket` çağrısı hata verir). Bir kütüphane ağa çıkmaya çalışırsa sessizce değil,
  açık bir hatayla durur. İşçiler zaten yalnızca stdin/stdout kullanır.
- Bu yüzden üretim sırasında ihtiyaç duyulan her şey (OmniVoice'un Whisper modeli dahil)
  **kurulum sırasında** indirilir; ilk kullanımda indirme yoktur.

**Şeffaflık:**

- README'de "Privacy" bölümü: veri akışı şeması, hangi adımda ağa çıkıldığı ve nereye
  (yalnızca PyPI ve Hugging Face), kullanıcının kendi doğrulama yöntemi.
- Kullanıcının kendi doğrulama yöntemi: modeller kurulduktan sonra internet bağlantısını kesip
  uygulamayı kullanmak — her şey çalışmaya devam etmelidir.
- Bilinen sınır (README'de yazılır): Windows'ta pencereyi gösteren Microsoft WebView2 bileşeni
  kendi tanılama verisini Microsoft'a gönderebilir; ses içeriği bu kapsamda değildir.
  Bundan kaçınmak isteyen kullanıcı aynı arayüzü kendi tarayıcısında açabilir.

### 5.4 Herkese açık repo

Repo GitHub'da herkese açıktır. Bu yüzden:

- Repoya hiçbir ses dosyası girmez: `.gitignore` yaygın ses biçimlerini (`*.wav`, `*.mp3`, `*.flac`, `*.ogg`, `*.m4a`, `*.webm`) dışlar. `samples/` yalnızca metin içerir.
- Commit'lerde kişisel e-posta görünmez: katkıda bulunanlara GitHub'ın "Keep my email addresses private" ayarı README'de önerilir.
- README'de iki bölüm zorunlu:
  - **Privacy:** veri akışı, ağa çıkılan tek anlar (kurulum: PyPI, Hugging Face, GitHub/uv), kullanıcının kendi doğrulama yöntemi (§5.3), bilinen sınırlar.
  - **Responsible use:** yalnızca kendi sesini veya izni olan sesleri kullanma; Chatterbox çıktılarındaki filigranın kaldırılmaması; hata bildirirken başkalarının ses kayıtlarını eklememe.
- Chatterbox'ın PerTh filigranı devre dışı bırakılmaz.

## 6. Kurulum ve kaldırma

**İlke:** Her şey proje klasöründe kalır. Projeyi silmek her şeyi siler.

```
.local/uv/                # uv'nin kendisi (gerekirse indirilir)
.local/uv-cache/          # UV_CACHE_DIR
.local/python/            # UV_PYTHON_INSTALL_DIR (uv'nin indirdiği Python)
.local/app/venv/          # arayüz ortamı
.local/<model>/venv/      # model ortamı
.local/<model>/cache/     # HF_HOME, TORCH_HOME
```

Kullanıcının önceden kurması gereken **hiçbir şey yok** (NVIDIA sürücüsü hariç).

- `start` betiği uv'yi şu sırayla arar: `.local/uv/` → sistemde kurulu uv.
- İkisi de yoksa, model kurulumundaki gibi önce bilgi verip onay ister (`[y/N]`, varsayılan Hayır),
  sonra uv'nin sabitlenmiş sürümünü GitHub'dan (astral-sh/uv) `.local/uv/` içine indirir.
  PATH'e ve sistem ayarlarına dokunulmaz.
- Python'u da uv indirir (`.local/python/`).

### Başlatma

`start.bat` (Windows) / `start.sh` (Linux): ortam değişkenlerini ayarlar, uv ile arayüz
ortamını kurar (yoksa), uygulamayı açar.

### "Kur" düğmesi

1. Onay kutusu gösterir:
   ```
   Chatterbox Multilingual (ResembleAI/chatterbox)
   Yaklaşık indirme: ~5–7 GB (kütüphaneler ~3–5 GB + model ~2 GB)
   Konum: .local/chatterbox/
   Lisans: MIT
   [Kur] [Vazgeç]
   ```
2. Onaylanırsa venv oluşturur, bağımlılıkları kurar, ağırlıkları indirir; ilerlemeyi bir
   log kutusunda canlı gösterir.
3. Sonunda gerçek disk kullanımını gösterir.

Boyutlar kodda küçük bir tablodadır ve "yaklaşık" diye etiketlenir.

### "Kaldır" düğmesi

Silinecek klasörü ve açılacak alanı gösterir, onay alınca işçiyi durdurur ve `.local/<model>/`
klasörünü siler.

## 7. Arayüz (tek sayfa)

Tüm arayüz metinleri İngilizce (bkz. V2).

```
┌ Models ─────────────────────────────────────────────┐
│ Chatterbox  ● installed (5.8 GB)   [Remove]          │
│ OmniVoice   ○ not installed        [Install]         │
│ [log box — visible during install]                   │
└─────────────────────────────────────────────────────┘
┌ Voice ──────────────────────────────────────────────┐
│ (•) Clone voice   ( ) Default voice                  │
│ [Upload file | Record]   duration: 12.4 s ✓          │  ← yalnızca Clone voice'ta
│ Reference transcript (optional, OmniVoice)           │  ← yalnızca Clone voice'ta
└─────────────────────────────────────────────────────┘
┌ Text ───────────────────────────────────────────────┐
│ [....................................]  [Generate]  │
└─────────────────────────────────────────────────────┘
┌ Results ────────────────────────────────────────────┐
│ Chatterbox  ▶ player  ⬇ download   (generated in 3.2 s)│
│ OmniVoice   ▶ player  ⬇ download                     │
└─────────────────────────────────────────────────────┘
```

- Kırpma: Gradio'nun yerleşik kırpma aracı (✂ ve ↺) kullanılır. Kendi kırpma aracımız denendi;
  hata verdi ve görsel olarak daha kötüydü, geri alındı (v1.7).
  - Bilinen görsel sorun (Gradio kaynaklı, kabul edildi): kırpmadan sonra turuncu seçim görünmeye devam edebilir.
  - README'de not: ↺ kaydı kırpılmamış hâline döndürür.
- Clone voice modunda referans 10 sn'den kısaysa "Generate" devre dışı ve uyarı gösterilir.
- Default voice modunda referans alanları gizlenir, 10 sn kontrolü uygulanmaz.
- Kurulu olmayan model sonuç bölümünde "not installed" yazar.
- Sayfanın altında kısa bir not: "Only use your own voice or voices you have permission to use."

## 8. Planlanan repo yapısı

```
vokalit/
├── CLAUDE.md
├── SPEC.md
├── README.md
├── LICENSE                    # Unlicense
├── start.sh / start.bat
├── app/
│   ├── requirements.txt       # gradio, pywebview
│   ├── main.py                # arayüz + pencere
│   └── models.py              # model tablosu, kur/kaldır, işçi yönetimi
├── workers/
│   ├── chatterbox/
│   │   ├── requirements.txt
│   │   └── worker.py
│   └── omnivoice/
│       ├── requirements.txt
│       └── worker.py
├── samples/                   # örnek Türkçe test metinleri (ses dosyası YOK)
├── outputs/                   # .gitignore'da
└── .local/                    # .gitignore'da
```

## 9. Başarı kriterleri (v1)

1. Temiz bir Windows veya Linux + NVIDIA makinede (uv ve Python kurulu değil): `start` çalıştır → uv indirme onayı → pencere açılır.
2. "Kur" onay kutusu model adı, yaklaşık boyut, konum ve lisansı gösteriyor; onay olmadan hiçbir şey indirilmiyor.
3. Dosyadan yüklenen ve mikrofondan kaydedilen ≥10 sn'lik referansla iki model de Türkçe `.wav` üretiyor ve pencerede dinlenebiliyor.
4. <10 sn referansta "Üret" çalışmıyor ve uyarı görünüyor.
5. Türkçe karakterli metin (ç, ğ, ı, İ, ö, ş, ü) doğru okunuyor — örnek metinle elle dinlenerek doğrulanır.
6. "Kaldır" sonrası `.local/<model>/` yok; ev dizininde (`~/.cache/huggingface`, `~/.cache/torch`, `~/.cache/pip`, `~/.cache/uv`) kurulum sırasında yeni dosya oluşmamış — öncesi/sonrası boyut karşılaştırmasıyla doğrulanır.
7. İkinci "Üret" çağrısı modeli yeniden yüklemiyor (ilkinden belirgin şekilde hızlı).
8. GPU yoksa anlaşılır bir hata mesajı gösteriliyor.
9. Default voice modunda referans ses vermeden iki model de Türkçe `.wav` üretiyor.
10. Kod tabanında (`app/`, `workers/`, betikler) Türkçe metin yok — Türkçe karakter araması (`grep -rP "[çğıİöşüÇĞÖŞÜ]"`) yalnızca `samples/` ve dokümanlarda sonuç veriyor.
11. Modeller kurulduktan sonra ağ bağlantısı kesikken iki mod da iki modelle çalışıyor.
12. Üretim sırasında `127.0.0.1` dışında hiçbir ağ bağlantısı açılmıyor — Linux'ta `ss -tnp`, Windows'ta Kaynak İzleyicisi > Ağ ile doğrulanır; uygulama kapandıktan sonra sistem geçici klasöründe ses dosyası kalmıyor.
13. Kayıt alanında bilgisayardaki mikrofonlar listeleniyor ve seçilebiliyor; kayıt durdurulunca kayıt pencerede dinlenebiliyor; temizle (✕) düğmesi kaydı/dosyayı kaldırıyor; "share" düğmesi yok; Gradio'nun kendi düğmeleri İngilizce ve düzgün görünüyor.
14. Kırpma: Gradio'nun ✂ aracıyla kırpılan kayıt, üretimde kırpılmış hâliyle kullanılıyor.
15. Repoda ses dosyası yok (`git ls-files | grep -iE "\.(wav|mp3|flac|ogg|m4a|webm)$"` boş) ve README'de Privacy ve Responsible use bölümleri var.

## 10. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| pywebview penceresinde mikrofon izni çalışmayabilir (özellikle Linux) | Mikrofonla kayıt yok | Plan adım 2'de erken test. Çalışmazsa: arayüzde "Tarayıcıda aç" düğmesi (aynı adres, varsayılan tarayıcı). |
| Linux'ta pywebview GTK/Qt sistem paketleri ister | Kurulum zorlaşır | README'de gerekli paket komutu; olmazsa tarayıcıda açılır. |
| Bir kütüphane `.local` dışına yazar | Kriter 6 bozulur | Adım 3/4'te ölçülür, gerekli ortam değişkeni eklenir. |
| Uzun metinde modelin sınırı | Kesik/bozuk çıktı | Adım 3/4'te sınır ölçülür; arayüzde karakter limiti olarak uygulanır. |

## 11. Uygulama planı

1. İskelet: klasörler, `start.sh/bat`, `.gitignore`, LICENSE → doğrula: `start` ile boş bir Gradio penceresi açılıyor.
2. pywebview + mikrofon testi → doğrula: Windows'ta pencerede mikrofonla kayıt yapılabiliyor (Linux sonucu not edilir).
3. Chatterbox işçisi + kur/kaldır → doğrula: kriter 2, 3, 6, 7 (Chatterbox için).
4. OmniVoice işçisi → doğrula: aynı kriterler (OmniVoice için).
5. Arayüz tamamlama (10 sn kontrolü, yan yana sonuç, hata mesajları) → doğrula: kriter 4, 5, 8.
6. Gerçek boyutları ölç, model tablosunu güncelle → doğrula: gösterilen tahmin ölçümle uyumlu.
7. README (TR + EN) → doğrula: kriter 1, temiz bir makinede adım adım.

Not: Paketler bu çalışma ortamında indirilemediği için 2–7. adımların doğrulaması kullanıcının makinesinde yapılır.

## 12. Varsayımlar

- V1: Python 3.11 (uv tarafından indirilir).
- V2: Kod tamamen İngilizce: değişken/fonksiyon adları, yorumlar, log/hata mesajları ve arayüz metinleri. Türkçe yalnızca `samples/` altındaki test metinlerinde ve dokümanlarda (SPEC, README'nin TR bölümü) bulunur.
- V3: Kullanıcı bir modeli kurmadan diğerini kullanabilir.

## 13. Açık sorular

Yok.

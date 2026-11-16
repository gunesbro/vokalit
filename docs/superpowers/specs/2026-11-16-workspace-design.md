# Vokalit Çalışma Alanı — Tasarım

Tarih: 2026-11-16 · Durum: taslak, onay bekliyor

> "*(öneri)*" ile işaretli maddeler kullanıcının değil, tasarımcının kararıdır; düzeltilebilir.

## 1. Amaç ve neden

Vokalit şu an tek seferlik bir araç: bir referans ses, bir metin, bir sonuç. Uygulama kapanınca
kayıt ve sonuçlar gidiyor. Hedef, insanların **geri dönüp devam edebildiği bir çalışma alanı**:

- Bir ses bir kez kaydedilip tekrar tekrar kullanılabilmeli.
- Üretilen her sesin **hangi sesle, hangi modelle, hangi metinle** üretildiği kayıt altında olmalı.
- Her çalışma ayrı bir **oturum** olmalı; eski oturumlara dönülebilmeli.
- **Podcast tarzı çok karakterli** işler yapılabilmeli.
- Aynı cümle **birden fazla modelle** üretilip karşılaştırılabilmeli (projenin çıkış noktası).

Üretilen sesle ne yapıldığı kullanıcının sorumluluğundadır; uygulama kullanım amacına karışmaz.

## 2. Hedefler / hedef olmayanlar / anti-hedefler

**Hedefler (bu sürüm)**
1. Oturumlar: oluştur, listele, aç, sil.
2. Oyuncu kadrosu: karakter adı → ses.
3. Senaryo: satırlar (karakter, metin, sonrasında duraklama).
4. Satır başına üretim; üretim anında model(ler) seçilir; her deneme (take) kaydedilir.
5. Denemeler arasından seçme (★), tek satırı yeniden üretme, deneme silme.
6. Dışa aktarma: seçili denemeler + duraklamalar → tek ses dosyası.
7. Ses kütüphanesi: kaydet/yükle, listele, dinle, sil.

**Hedef olmayanlar (sonraki sürümler)**
- Duygu/ifade ayarları (Chatterbox duygu yoğunluğu, OmniVoice `[laughter]` etiketleri).
- Rakamları kelimeye çevirme.
- Satırları sürükle-bırak ile sıralama, klavye kısayolları.
- Ses yeniden adlandırma.
- OmniVoice (ayrı adım; bu tasarım onu taşıyabilecek şekilde kurulur).

**Anti-hedefler (çalışsa bile başarısızlık sayılır)**
- Ses, metin veya çıktı bilgisayardan çıkar.
- Kullanıcının emeği kaybolur (kaydedilmemiş senaryo, silinen kayıt, kapanınca giden çıktılar).
- Modelin desteklemediği bir şeyi destekliyormuş gibi gösteren arayüz (ör. çalışmayan serbest "talimat" kutusu).

## 3. Kısıtlar

- Gradio 6 + pywebview penceresi (mevcut yapı). Açılır pencereler (toast) uygulama penceresinde görünmüyor; mesajlar sayfada gösterilir.
- Modeller ayrı süreçlerde (işçiler), mevcut JSON protokolüyle (SPEC §5.2). İşçi tarafında değişiklik gerekmez.
- Her iki model de 24 kHz mono çıktı verir.
- Kod ve arayüz İngilizce; kullanıcı verisi (karakter adları, metinler) herhangi bir dilde olabilir.
- Herkese açık repo: kullanıcı verisi hiçbir koşulda git'e girmez.

## 4. Yaklaşımlar

| | A) Gradio ile devam (**seçildi**) | B) Kendi web arayüzü |
|---|---|---|
| Nasıl | `@gr.render` ile satır sayısına göre çizilen senaryo editörü | Aynı pencerede HTML/JS arayüz + küçük Python sunucusu |
| Artı | Mevcut kod üzerine; tek dil; kayıt, kırpma, oynatıcı hazır | Tam kontrol, akıcı editör |
| Eksi | Gradio tuhaflıkları; sürükle-bırak yok; uzun senaryolarda yavaşlayabilir | Kod 3–4 kat; kayıt/kırpma/dalga görünümü sıfırdan |

Elenen: Gradio özel bileşeni (JS derleme ortamı gerektirir; B'nin zorluğu + A'nın sınırları).

**Seçim A**, kullanıcı kararı: "şimdilik Gradio ile ilerleyip nasıl bir sonuç alacağımızı görelim."
Depolama ve model katmanları arayüzden bağımsız tutulur; gerekirse yalnızca arayüz B'ye taşınır.

## 5. Kullanıcının kararları

- Her üretim kaydedilir; hangi ses, model ve metinle üretildiği hatırlanır.
- Oturumlar ayrı; eskilerine dönülebilir.
- Çok karakterli (podcast tarzı) işler kapsamda.
- Model **üretim anında** seçilir; aynı satır birden fazla modelle üretilebilir.
- Hangi modelle üretildiği kaydedilir ve **dosya adında ipucu** olarak bulunur.
- Arayüz teknolojisi: Gradio.

## 6. Veri modeli ve depolama

Tüm kullanıcı verisi proje kökünde `workspace/` altında *(öneri: tek klasör = kolay yedekleme ve tek `.gitignore` satırı)*.
SPEC §7.1'deki kök `voices/` buraya taşınır.

```
workspace/
├── voices/<voice-id>/
│   ├── voice.wav
│   └── voice.json          # {"name", "created", "duration", "source": "recording"|"upload"}
└── sessions/<session-id>/
    ├── session.json
    ├── takes/*.wav
    └── exports/*.wav
```

- `<voice-id>`, `<session-id>`: oluşturulma zamanı (`20261116-161400`); çakışırsa `-2`, `-3` eklenir.
- Dosyalar okunabilir JSON'dur *(öneri: şeffaflık — kullanıcı neyin nerede olduğunu görebilir)*.

### session.json

```json
{
  "name": "Episode 1",
  "created": "2026-11-16T16:14:00",
  "cast": [
    {"id": "c1", "name": "Host",  "voice": "20261116-142530"},
    {"id": "c2", "name": "Guest", "voice": "default"}
  ],
  "lines": [
    {
      "id": "l1",
      "character": "c1",
      "text": "Bugün yerel yapay zekayı konuşuyoruz.",
      "pause_after": 0.5,
      "selected": "takes/01-host-chatterbox-take2.wav",
      "takes": [
        {
          "file": "takes/01-host-chatterbox-take2.wav",
          "model": "chatterbox",
          "voice": "20261116-142530",
          "voice_name": "Recording 2026-11-16 14:25:30",
          "text": "Bugün yerel yapay zekayı konuşuyoruz.",
          "created": "2026-11-16T16:20:11",
          "generation_seconds": 2.1,
          "duration": 3.4
        }
      ]
    }
  ]
}
```

- **Deneme kaydı bir anlık görüntüdür:** metin, ses adı ve model deneme anındaki hâliyle saklanır. Satır sonradan düzenlenirse veya ses kütüphaneden silinirse geçmiş doğru kalır.
- `"voice": "default"` = modelin yerleşik sesi. OmniVoice'ta bu her üretimde rastgele bir ses demektir (arayüzde not edilir).
- **Dosya adı** *(öneri)*: `<satır no 2 hane>-<karakter-slug>-<model>-take<n>.wav`. Satır numarası üretim anındaki sıradır; satırlar sonradan yer değiştirirse ad güncellenmez (yalnızca ipucu; doğru bilgi `session.json`'dadır). Slug: küçük harf, ASCII'ye indirgenmiş, harf/rakam dışı `-`.
- **Otomatik kayıt:** her değişiklikte `session.json` hemen yazılır (önce geçici dosyaya, sonra yeniden adlandırma — yarım yazılmış dosya olmaz). "Save" düğmesi yoktur.

## 7. Ekranlar

İki sekme: **Studio** ve **Voices**. Models bölümü (kur/kaldır) Studio'nun üstünde, katlanabilir *(öneri)*.

### 7.1 Studio

```
┌ Sessions ─────────┐ ┌ Episode 1 ─────────────────────────────────────────────────┐
│ ● Episode 1       │ │ Cast                                                       │
│   Intro test      │ │  Host  [Recording 2026-11-16 14:25 ▾]   [✕]                │
│   ...             │ │  Guest [Default voice ▾]                [✕]   [+ Character]│
│ [+ New session]   │ │                                                            │
│                   │ │ Models: [✓] Chatterbox  [ ] OmniVoice                      │
│ [Delete session]  │ │                                                            │
└───────────────────┘ │ 1 [Host ▾] [Bugün yerel yapay zekayı...] pause [0.5] ↑↓✕   │
                      │   Takes: ▶ chatterbox #1   ▶ chatterbox #2 ★   [Generate]  │
                      │ 2 [Guest▾] [Kulağa güzel geliyor.      ] pause [0.3] ↑↓✕   │
                      │   Takes: (none)                                [Generate]  │
                      │ [+ Line]   [Paste script…]                                 │
                      │                                                            │
                      │ [Generate missing lines]   [Export]   message line         │
                      └────────────────────────────────────────────────────────────┘
```

- **Sessions:** liste (en yeni üstte), yeni oturum (ad sorulur, varsayılan "Session 2026-11-16 16:14"), silme (onaylı, kalıcı: klasör silinir). Oturum adı başlıkta düzenlenebilir *(öneri)*.
- **Cast:** karakter ekle/sil, her karaktere ses seç (kütüphanedeki sesler + "Default voice"). Satırlarda kullanılan bir karakter silinemez (mesajla açıklanır).
- **Models:** kurulu modellerin onay kutuları (varsayılan: kurulu ilk model işaretli *(öneri)*); satır üretimi ve toplu üretim seçili modellerin **her biriyle** birer deneme üretir.
- **Satır:** karakter, metin, duraklama (sn, varsayılan 0.3 *(öneri)*), yukarı/aşağı, sil.
- **Takes:** her deneme bir oynatıcı + etiket (model, deneme no), ★ seç, sil. İlk deneme otomatik seçili olur; sonra kullanıcı değiştirir. Seçili deneme silinirse en yeni kalan deneme seçilir *(öneri)*. Satırın metni denemenin metninden farklıysa denemede "text changed" işareti görünür *(öneri: Export eski metni okuyan bir denemeyi sessizce kullanmasın)*.
- **Paste script…** *(öneri)*: `Karakter: metin` biçiminde satırlar yapıştırılır; karakterler yoksa kadroya "Default voice" ile eklenir, satırlar sona eklenir. Podcast senaryosunu tek tek satır eklemeden almak için.
- **Generate missing lines:** hiç denemesi olmayan satırları sırayla üretir; ilerleme mesaj satırında ("Line 3/12…"). Bir **Stop** düğmesi, o anki satır bitince durdurur *(öneri)*.
- **Export:** her satırın seçili denemesi + `pause_after` sessizliği sırayla birleştirilir → `exports/<oturum-slug>-<zaman>.wav`, indirme oynatıcısıyla gösterilir. Denemesi olmayan satır varsa dışa aktarma yapılmaz, mesajda hangi satırlar olduğu yazılır.

### 7.2 Voices

```
┌ Add a voice ─────────────────────────────┐ ┌ Library ───────────────────────────────┐
│ [Upload | Record] (Gradio trim available)│ │ Recording 2026-11-16 14:25  12.4 s  ▶ │
│ Name [Recording 2026-11-16 16:30     ]   │ │   used in 2 sessions          [Delete]│
│ [Save to library]                        │ │ intro-sample                 15.0 s  ▶ │
│ Only use your own voice or voices you    │ │   not used                    [Delete]│
│ have permission to use.                  │ └────────────────────────────────────────┘
└──────────────────────────────────────────┘
```

- **Kaydetme:** SPEC §7.1'deki "her kayıt otomatik kaydedilir" yerine açık bir **Save to library** düğmesi *(öneri)*. Sebep: kayıt artık ayrı bir sekmede yapılıyor ve kullanıcı adı burada veriyor; kırpmadan önce otomatik kaydetmek yarım kayıtlar biriktirir. **Kullanıcı onayı gerekir** (önceki karar "hepsi kütüphaneye eklensin" idi).
- 10 sn'den kısa ses kaydedilmez (mesajla süre söylenir).
- **Silme:** onaylı, kalıcı. Ses bir kadroda kullanılıyorsa onay metni hangi oturumlarda kullanıldığını söyler; silinince o karakterler "Default voice"a döner. Eski denemelerin kaydı (`voice_name`) korunur.

## 8. Üretim akışı

1. Satır için: karakterin sesi → `ref` (kütüphanedeki `voice.wav` yolu) veya `None` (default).
2. Seçili her model için mevcut işçi protokolüyle istek; çıktı doğrudan `takes/` altına yazılır.
3. Deneme `session.json`'a eklenir; satırın seçili denemesi yoksa bu olur.
4. Bir model hata verirse diğer modeller devam eder; hata mesaj satırında gösterilir.

## 9. Gizlilik

- `workspace/` `.gitignore`'da; kök `voices/` satırı kaldırılır.
- Geçici klasör (`.local/tmp`) davranışı aynı kalır; kütüphaneye kaydedilen ses `workspace/voices/` altına **kopyalanır**.
- *(öneri)* Açılışta proje yolu bir bulut eşitleme klasöründeyse (OneDrive, Dropbox, iCloud Drive, Google Drive — yol adından ve Windows'ta `OneDrive` ortam değişkenlerinden tespit) Studio'nun üstünde kalıcı bir uyarı gösterilir: kayıtlar buluta yüklenebilir.

## 10. Mevcut kodla ilişkisi

- `app/models.py` (kur/kaldır, işçiler) değişmez.
- `app/main.py` arayüzü yeniden yazılır; depolama yeni bir `app/workspace.py` modülünde (oturum/ses okuma-yazma, dışa aktarma) — arayüzden bağımsız, Gradio'suz test edilebilir.
- `outputs/` klasörü kalkar (yerini `takes/` ve `exports/` alır). Henüz kullanıcı olmadığı için taşıma (migration) yok.
- SPEC.md bu tasarım onaylanınca güncellenir (§7 ve §7.1 yerine bu yapı).

## 11. Başarı kriterleri

1. İki karakterli, 3 satırlık bir oturum oluşturulur; uygulama kapatılıp açılınca her şey (kadro, satırlar, denemeler, seçimler) aynen geri gelir.
2. Bir satır iki modelle üretilince iki deneme oluşur; etiketleri ve dosya adları modeli gösterir.
3. Bir satır yeniden üretilince yeni deneme eklenir, eskiler kalır; ★ ile seçim değişir.
4. Export, seçili denemeleri ve duraklamaları doğru sırayla tek dosyada birleştirir (süre = denemeler + duraklamalar).
5. Satır metni değiştirilince eski denemenin kaydında eski metin kalır.
6. Kütüphaneden silinen ses, eski denemelerin `voice_name` bilgisini bozmaz; kadrodaki karakter "Default voice"a döner.
7. `git status` `workspace/` içeriğini hiç göstermez.
8. `app/workspace.py` için Gradio'suz birim testleri (oturum oluşturma, kaydetme/yükleme, export birleştirme, silme).

## 12. İnşa edene bırakılanlar

- Gradio bileşenlerinin tam yerleşimi ve düğme metinleri (taslaklar yön gösterir).
- Uzun senaryolarda `@gr.render` performansı ölçülür; yavaşsa sayfalama/katlama eklenebilir (kullanıcıya sorularak).
- Slug ve ID üretiminin ayrıntıları.

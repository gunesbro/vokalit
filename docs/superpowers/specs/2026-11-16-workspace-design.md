# Vokalit Çalışma Alanı — Tasarım

Tarih: 2026-11-16 · Durum: taslak v2, onay bekliyor

> "*(öneri)*" ile işaretli maddeler kullanıcının değil, tasarımcının kararıdır; düzeltilebilir.

## 1. Amaç ve neden

Vokalit şu an tek seferlik bir araç: bir referans ses, bir metin, bir sonuç. Uygulama kapanınca
kayıt ve sonuçlar gidiyor. Hedef, insanların **geri dönüp devam edebildiği bir çalışma alanı**:

- Bir ses (karakter) bir kez oluşturulup birden fazla oturumda tekrar tekrar kullanılabilmeli.
- Üretilen her sesin **hangi karakter/örnekle, hangi modelle, hangi metinle** üretildiği kayıt altında olmalı.
- Her çalışma ayrı bir **oturum** olmalı; eski oturumlara dönülebilmeli.
- **Podcast tarzı çok karakterli** işler yapılabilmeli.
- Aynı cümle **birden fazla modelle** üretilip karşılaştırılabilmeli (projenin çıkış noktası).
- Duygu ve vurgu, modellerin **gerçekten yapabildiği** yollarla kontrol edilebilmeli: karakter başına
  birden fazla ses örneği (ör. "calm", "excited") ve kullanıcının kendi seslendirdiği repliği karakterin
  sesine dönüştürme.

Üretilen sesle ne yapıldığı kullanıcının sorumluluğundadır; uygulama kullanım amacına karışmaz.

## 2. Hedefler / hedef olmayanlar / anti-hedefler

**Hedefler (bu sürüm)**
1. Oturumlar: oluştur, listele, aç, yeniden adlandır, sil.
2. Karakterler: oturumlardan bağımsız kütüphane; her karakterde bir veya birden fazla etiketli ses örneği.
3. Oturum kadrosu: kütüphaneden karakterler + oturuma özel karakterler; **Save as character** düğmesiyle kütüphaneye taşıma.
4. Senaryo: satırlar (karakter, örnek, metin, sonrasında duraklama).
5. Satır başına üretim; üretim anında model(ler) seçilir; her deneme (take) kaydedilir.
6. **Ses dönüştürme (Chatterbox VC):** kullanıcı satırı kendisi kaydeder, karakterin sesine dönüştürülür; sonuç o satırın bir denemesi olur.
7. **Seed:** her deneme kullandığı seed'i kaydeder; aynı seed ile tekrar üretilebilir.
8. Denemeler arasından seçme (★), tek satırı yeniden üretme, deneme silme.
9. Dışa aktarma: seçili denemeler + duraklamalar → tek ses dosyası.

**Hedef olmayanlar (sonraki sürümler)**
- OmniVoice ile gelecekler: ses tasarımı (tariften karakter), kayıt hazırlama (gürültü temizleme,
  normalleştirme, otomatik yazıya dökme). Bu tasarım onları taşıyabilecek şekilde kurulur.
- Duygu yoğunluğu ayarı, `[laughter]` gibi etiketler, rakamları kelimeye çevirme.
- Ses efektleri, model eğitimi, dil modeliyle metin önerisi.
- Satırları sürükle-bırak ile sıralama, klavye kısayolları.
- Bulut eşitleme klasörü uyarısı (kullanıcı kararı: gerek yok).

**Anti-hedefler (çalışsa bile başarısızlık sayılır)**
- Ses, metin veya çıktı bilgisayardan çıkar.
- Kullanıcının emeği kaybolur (kaydedilmemiş senaryo, kaybolan kayıt, kapanınca giden çıktılar).
- Modelin desteklemediği bir şeyi destekliyormuş gibi gösteren arayüz (ör. çalışmayan serbest "talimat" kutusu).

## 3. Kısıtlar

- Gradio 6 + pywebview penceresi (mevcut yapı). Açılır pencereler (toast) uygulama penceresinde görünmüyor; mesajlar sayfada gösterilir.
- Modeller ayrı süreçlerde (işçiler), JSON satır protokolüyle (SPEC §5.2); bu tasarım protokole iki alan ekler (§8).
- Modeller üretim başına **tek** referans kaydı alır; birden fazla örnek, satır başına hangisinin kullanılacağının seçilmesi demektir (birleştirilmez).
- Her iki model de 24 kHz mono çıktı verir.
- Kod ve arayüz İngilizce; kullanıcı verisi (karakter adları, etiketler, metinler) herhangi bir dilde olabilir.
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
- Model **üretim anında** seçilir; aynı satır birden fazla modelle üretilebilir; model kaydedilir ve **dosya adında ipucu** olarak bulunur.
- Arayüz teknolojisi: Gradio.
- Karakterler oturumlardan ayrı oluşturulabilir; oturum içinde oluşturulan karakter **düğmeyle** kütüphaneye taşınır, taşınmazsa yalnızca o oturumda kalır.
- Bir karaktere birden fazla ses kaydı verilebilir.
- Bulut klasörü uyarısı yok.
- Bu sürüme: ses dönüştürme ve seed. OmniVoice adımına: ses tasarımı ve kayıt hazırlama.

## 6. Veri modeli ve depolama

Tüm kullanıcı verisi proje kökünde `workspace/` altında *(öneri: tek klasör = kolay yedekleme ve tek `.gitignore` satırı)*.

```
workspace/
├── characters/<character-id>/
│   ├── character.json
│   └── samples/<sample-id>.wav
└── sessions/<session-id>/
    ├── session.json
    ├── characters/<character-id>/...   # oturuma özel karakterler, aynı yapı
    ├── recordings/*.wav                # ses dönüştürme için kullanıcının kendi kayıtları
    ├── takes/*.wav
    └── exports/*.wav
```

- ID'ler oluşturulma zamanından türetilir (`20261116-161400`); çakışırsa `-2`, `-3` eklenir.
- Oturuma özel karakter, kütüphanedekiyle **aynı yapıdadır**; "Save as character" klasörü `workspace/characters/` altına taşır ve oturumdaki referansı günceller.
- Dosyalar okunabilir JSON'dur *(öneri: şeffaflık — kullanıcı neyin nerede olduğunu görebilir)*.

### character.json

```json
{
  "name": "Burak",
  "created": "2026-11-16T16:30:00",
  "default_sample": "s1",
  "samples": [
    {"id": "s1", "label": "calm",    "file": "samples/s1.wav", "duration": 12.4, "source": "recording", "created": "..."},
    {"id": "s2", "label": "excited", "file": "samples/s2.wav", "duration": 11.0, "source": "upload",    "created": "..."}
  ]
}
```

- Karakterin örneği olmayabilir: o zaman **modelin varsayılan sesini** kullanır (OmniVoice'ta bu her üretimde rastgele bir ses demektir; arayüzde not edilir).

### session.json

```json
{
  "name": "Episode 1",
  "created": "2026-11-16T16:14:00",
  "cast": [
    {"character": "20261116-163000", "scope": "library"},
    {"character": "20261116-164500", "scope": "session"}
  ],
  "lines": [
    {
      "id": "l1",
      "character": "20261116-163000",
      "sample": null,
      "text": "Bugün yerel yapay zekayı konuşuyoruz.",
      "pause_after": 0.3,
      "selected": "takes/01-burak-chatterbox-take2.wav",
      "takes": [
        {
          "file": "takes/01-burak-chatterbox-take2.wav",
          "kind": "tts",
          "model": "chatterbox",
          "character_name": "Burak",
          "sample_label": "calm",
          "text": "Bugün yerel yapay zekayı konuşuyoruz.",
          "seed": 1234567,
          "created": "2026-11-16T16:20:11",
          "generation_seconds": 2.1,
          "duration": 3.4
        },
        {
          "file": "takes/01-burak-chatterbox-vc-take3.wav",
          "kind": "convert",
          "model": "chatterbox-vc",
          "character_name": "Burak",
          "sample_label": "calm",
          "source_recording": "recordings/01-take3.wav",
          "created": "...", "generation_seconds": 1.2, "duration": 3.6
        }
      ]
    }
  ]
}
```

- `line.sample`: `null` = karakterin varsayılan örneği; yoksa örnek ID'si.
- **Deneme kaydı bir anlık görüntüdür:** metin, karakter adı, örnek etiketi, model ve seed deneme anındaki hâliyle saklanır. Satır sonradan düzenlenirse veya karakter/örnek silinirse geçmiş doğru kalır.
- **Dosya adı** *(öneri)*: `<satır no 2 hane>-<karakter-slug>-<model>-take<n>.wav`. Satır numarası üretim anındaki sıradır; satırlar sonradan yer değiştirirse ad güncellenmez (yalnızca ipucu; doğru bilgi `session.json`'dadır). Slug: küçük harf, ASCII'ye indirgenmiş, harf/rakam dışı `-`.
- **Otomatik kayıt:** her değişiklikte `session.json` / `character.json` hemen yazılır (önce geçici dosyaya, sonra yeniden adlandırma — yarım yazılmış dosya olmaz). "Save" düğmesi yoktur.

## 7. Ekranlar

İki sekme: **Studio** ve **Characters**. Models bölümü (kur/kaldır) Studio'nun üstünde, katlanabilir *(öneri)*.

### 7.1 Studio

```
┌ Sessions ─────────┐ ┌ Episode 1 ─────────────────────────────────────────────────────┐
│ ● Episode 1       │ │ Cast                                                           │
│   Intro test      │ │  Burak  (library)                                    [✕]       │
│   ...             │ │  Guest  (this session)  [Save as character]          [✕]       │
│ [+ New session]   │ │  [+ Add from library ▾]  [+ New character in session]          │
│                   │ │                                                                │
│ [Delete session]  │ │ Models: [✓] Chatterbox  [ ] OmniVoice     Seed: [random ]      │
└───────────────────┘ │                                                                │
                      │ 1 [Burak ▾][calm ▾] [Bugün yerel yapay zekayı...] pause[0.3] ↑↓✕│
                      │   Takes: ▶ chatterbox #1 ▶ chatterbox #2 ★  [Generate] [Convert]│
                      │ 2 [Guest ▾][—    ] [Kulağa güzel geliyor.       ] pause[0.3] ↑↓✕│
                      │   Takes: (none)                             [Generate] [Convert]│
                      │ [+ Line]   [Paste script…]                                     │
                      │                                                                │
                      │ [Generate missing lines] [Stop]  [Export]   message line       │
                      └────────────────────────────────────────────────────────────────┘
```

- **Sessions:** liste (en yeni üstte), yeni oturum (varsayılan ad "Session 2026-11-16 16:14"), ad başlıkta düzenlenebilir *(öneri)*, silme (onaylı, kalıcı: klasör silinir; oturuma özel karakterler de gider — onay metni bunu söyler).
- **Cast:**
  - **Add from library:** kütüphanedeki karakteri kadroya ekler (kopyalamaz, referans verir).
  - **New character in session:** oturuma özel karakter (ad + isteğe bağlı örnek; örnek eklemek Characters sekmesindeki aynı bileşenle, kadro içinde açılan küçük bir panelde).
  - **Save as character:** oturuma özel karakteri kütüphaneye taşır; diğer oturumlarda kullanılabilir olur.
  - Satırlarda kullanılan bir karakter kadrodan çıkarılamaz (mesajla açıklanır).
- **Models:** kurulu modellerin onay kutuları (varsayılan: kurulu ilk model işaretli *(öneri)*); satır üretimi ve toplu üretim seçili modellerin **her biriyle** birer deneme üretir.
- **Seed:** boş = rastgele (kullanılan değer denemeye kaydedilir); dolu = o değer. Bir denemenin seed'i tek tıkla bu alana kopyalanabilir *(öneri)*.
- **Satır:** karakter, örnek (karakterin örnekleri; varsayılan "default"), metin, duraklama (sn, varsayılan 0.3 *(öneri)*), yukarı/aşağı, sil.
- **Takes:** her deneme bir oynatıcı + etiket (model veya "converted", deneme no, örnek etiketi), ★ seç, sil. İlk deneme otomatik seçili olur. Seçili deneme silinirse en yeni kalan seçilir *(öneri)*. Satırın metni denemenin metninden farklıysa denemede "text changed" işareti görünür *(öneri)*.
- **Convert:** satırın altında kayıt/yükleme alanı açılır; kullanıcı repliği kendisi seslendirir; Chatterbox VC ile satırın karakter/örneğine dönüştürülür. Kullanıcının kaydı `recordings/` altında saklanır (yeniden dönüştürmek için).
- **Paste script…** *(öneri)*: `Karakter: metin` biçimindeki satırlar yapıştırılır; kadroda olmayan karakterler **oturuma özel** karakter olarak (örneksiz) eklenir, satırlar sona eklenir.
- **Generate missing lines:** hiç denemesi olmayan satırları sırayla üretir; ilerleme mesaj satırında ("Line 3/12…"). **Stop**, o anki satır bitince durdurur *(öneri)*.
- **Export:** her satırın seçili denemesi + `pause_after` sessizliği sırayla birleştirilir → `exports/<oturum-slug>-<zaman>.wav`, oynatıcı + indirme ile gösterilir. Denemesi olmayan satır varsa dışa aktarma yapılmaz, mesajda hangi satırlar olduğu yazılır.

### 7.2 Characters

```
┌ Characters ─────────┐ ┌ Burak ───────────────────────────────────────────────────────┐
│ ● Burak   2 samples │ │ Name [Burak                ]         used in 2 sessions      │
│   Narrator 1 sample │ │ Samples                                                      │
│   ...               │ │  ★ calm      12.4 s  ▶  label[calm     ]           [Delete]  │
│ [+ New character]   │ │    excited   11.0 s  ▶  label[excited  ]           [Delete]  │
│                     │ │ Add a sample: [Upload | Record] (Gradio trim available)      │
│                     │ │   → added automatically when recording stops / upload ends   │
│                     │ │ Only use your own voice or voices you have permission to use.│
│                     │ │ [Delete character]                                           │
└─────────────────────┘ └──────────────────────────────────────────────────────────────┘
```

- Yeni kayıt/yükleme bitince **otomatik olarak** örnek olur (kullanıcı kararıyla uyumlu); etiketi varsayılan "sample N", sonradan düzenlenir. ★ varsayılan örneği seçer.
- Kırpma: Gradio'nun aracıyla, kayıt alanında yapılır. Gradio kırpma sonrası yeni bir olay tetikliyorsa kırpılmış hâl aynı örneğin üzerine yazılır; tetiklemiyorsa *(öneri)* eklenmiş örnek kırpılmaz, yeniden kaydedilir (inşa sırasında doğrulanır).
- 10 sn'den kısa ses örnek olarak eklenmez (mesajla süre söylenir).
- **Karakter silme:** onaylı, kalıcı. Kullanıldığı oturumlar onay metninde listelenir; silinince o oturumlarda karakter "deleted character" olarak görünür, satırları kalır ama yeni üretim için başka karakter seçilmesi gerekir *(öneri)*. Eski denemelerin kaydı korunur.
- **Örnek silme:** onaylı; o örneği kullanan satırlar varsayılan örneğe döner.

## 8. Üretim akışı ve işçi protokolü

**Metinden ses (tts):**
1. Satırın karakteri ve örneği → `ref` (örnek dosyası yolu) veya `None` (örneksiz karakter → model varsayılan sesi).
2. Seed belirlenir (alan boşsa rastgele).
3. Seçili her model için işçiye istek; çıktı doğrudan `takes/` altına yazılır.
4. Deneme `session.json`'a eklenir; satırın seçili denemesi yoksa bu olur.
5. Bir model hata verirse diğerleri devam eder; hata mesaj satırında gösterilir.

**Ses dönüştürme (convert):** kullanıcı kaydı `recordings/` altına kaydedilir → Chatterbox işçisine dönüştürme isteği → deneme (`kind: "convert"`, `model: "chatterbox-vc"`).

**Protokol eklemeleri (SPEC §5.2):**

```
→ {"text": "...", "ref": "<yol>|null", "out": "<yol>", "seed": 1234567}                   # tts
→ {"task": "convert", "source": "<yol>", "ref": "<yol>|null", "out": "<yol>"}             # yalnızca Chatterbox
← {"ok": true, "out": "<yol>", "seconds": 1.2}
```

- `task` yoksa `tts` kabul edilir (geriye uyumlu).
- Chatterbox işçisi seed'i üretimden önce `torch.manual_seed` (+ CUDA) ile uygular.
- Dönüştürme modeli (`ChatterboxVC`) ilk dönüştürme isteğinde yüklenir, sonra açık kalır. Varsayılan ses için `ref: null` → VC'nin yerleşik sesi.
- **Kurulum:** VC model dosyalarının da kurulumda indirilmesi gerekir (`--download` adımı VC'yi de yükler). Mevcut Chatterbox kurulumları yeniden kurulmalı (şu an tek kullanıcı var). Hangi dosyaların ek olarak indiği ve ölçülen boyut inşa sırasında doğrulanır.

## 9. Gizlilik

- `workspace/` `.gitignore`'da; kök `voices/` satırı kaldırılır.
- Geçici klasör (`.local/tmp`) davranışı aynı kalır; karakter örnekleri ve dönüştürme kayıtları `workspace/` altına **kopyalanır**.
- Ses dönüştürme de işçide, ağ engeli altında çalışır.

## 10. Mevcut kodla ilişkisi

- `app/models.py`: kurulum/işçi yönetimi aynı; `generate()` seed alır, yeni `convert()` eklenir.
- `workers/chatterbox/worker.py`: seed, `task: "convert"`, `--download`'da VC.
- `app/main.py` arayüzü yeniden yazılır; depolama yeni bir `app/workspace.py` modülünde (oturum/karakter okuma-yazma, dışa aktarma) — arayüzden bağımsız, Gradio'suz test edilebilir.
- `outputs/` klasörü kalkar (yerini `takes/` ve `exports/` alır). Henüz kullanıcı olmadığı için taşıma yok.
- SPEC.md bu tasarım onaylanınca güncellenir (§7 ve §7.1 yerine bu yapı).

## 11. Başarı kriterleri

1. İki karakterli (biri kütüphaneden, biri oturuma özel), 3 satırlık bir oturum oluşturulur; uygulama kapatılıp açılınca her şey (kadro, satırlar, örnek seçimleri, denemeler, ★) aynen geri gelir.
2. Bir satır iki modelle üretilince iki deneme oluşur; etiketleri ve dosya adları modeli gösterir.
3. Bir satır yeniden üretilince yeni deneme eklenir, eskiler kalır; ★ ile seçim değişir.
4. Aynı metin, örnek, model ve seed ile iki üretim aynı sesi verir (Chatterbox için doğrulanır).
5. Bir karakterin iki örneğiyle ("calm", "excited") üretilen denemeler kulakla ayırt edilebilir ve kayıtlarında doğru etiket yazar.
6. Convert: kullanıcının kaydı karakterin sesine dönüşür; deneme `converted` olarak görünür; kaynak kayıt `recordings/` altındadır.
7. "Save as character" sonrası karakter başka bir oturumun kadrosuna eklenebilir; ilk oturum onu kütüphaneden kullanmaya devam eder.
8. Export, seçili denemeleri ve duraklamaları doğru sırayla tek dosyada birleştirir (süre = denemeler + duraklamalar).
9. Satır metni değiştirilince eski denemenin kaydında eski metin kalır ve "text changed" görünür.
10. Silinen karakter/örnek, eski denemelerin kayıtlarını bozmaz.
11. `git status` `workspace/` içeriğini hiç göstermez.
12. `app/workspace.py` için Gradio'suz birim testleri (oturum/karakter oluşturma, kaydet/yükle, Save as character, export birleştirme, silme).

## 12. İnşa edene bırakılanlar

- Gradio bileşenlerinin tam yerleşimi ve düğme metinleri (taslaklar yön gösterir).
- Uzun senaryolarda `@gr.render` performansı ölçülür; yavaşsa sayfalama/katlama eklenebilir (kullanıcıya sorularak).
- Slug ve ID üretiminin ayrıntıları.
- VC model dosyalarının hangi isimlerle indiği ve kurulum boyutuna etkisi.

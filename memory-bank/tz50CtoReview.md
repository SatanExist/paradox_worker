# CTO-разбор ТЗ 5.0 (без кода)

> **Статус:** разбор 2026-08-26; шлюз FAL внедрён 2026-08-27 (`studio_bridge/gateway.py`). Код по ТЗ 5.0 greenfield **не** писать.  
> **Вход:** «Game-Ready 3D AI Multi-Model Hub» v5.0 Production Blueprint.  
> **Это не юрконсультация.** ToS — публичные страницы; COGS T2 — наши замеры в `systemPatterns.md` / `activeContext.md`.

Связанный ресерч: канвас условий API (сессия 2026-08-26), Hitem3D ToS §3.4a, Meshy ToS, FAL API Services, Hunyuan community license (EU/UK/KR вне Territory).

---

## Вердикт одной фразой

Кабинет + кредиты + опциональная доводка сетки — **да**.  
Meshy и Hunyuan **на FAL** (ключ на бэкенде) — **да**; веса Hunyuan и consumer-ключи meshy.ai — **нет**.  
Новый монорепо `/backend` `/frontend` `/worker_cpp` в **paradox_worker** — **нет**: фронт = AI_MESH, GPU уже здесь.

Документ полезен как черновик кабинета и кредитной модели. Как production blueprint — нет: цифры не сходятся с замерами, часть провайдеров запрещена правилами, стек дублирует живой, C++-ремеш не «ров».

---

## Что в ТЗ верно (оставить)

- Рынок фрагментирован; сырой GLB часто не готов к Unreal/Unity без доводки.
- Свою фундамент-сеть с нуля на этапе проверки продукта не тянуть.
- Безлимит $15–30/мес — риск сжечь маржу. Кредиты, которые не сгорают — ок как модель.
- Шлюз провайдеров (`generate` / `check_status` / webhook) — нормальный паттерн. Зародыш уже есть: `scripts/studio_api.py` + `studio_bridge/`.
- GLB на Cloudflare R2 — уже прод-путь T2, не «придумать S3».
- Потребительские ключи Meshy/Rodin для перепродажи — правильно исключены (Meshy: competitive + resell).
- Replicate как ядро — справедливо не брать (холодный старт).

---

## Что ложно или опасно

### Юридика (риски не минимизированы)

| В ТЗ | Факт |
|------|------|
| Hunyuan3D веса на RunPod | Community license: EU / UK / Korea **вне Territory, включая Output**. У нас стоп. Tencent Cloud HY 3D — другой продукт и договор, не «скачать веса». |
| Tripo P1 «B2B» по ~$0.08 | Публичный Developer API есть. Сайт-ToS: нельзя отдавать foundation-сервис **end users** без письменного согласия. Без письма это не B2B. |
| fal.ai Rodin ~$0.40 | FAL **разрешает** юзеров через ваш бэкенд (ключ не в браузер). Легальнее Tripo/Meshy «с улицы». Не default quality вместо T2. Проверить Partner-флаг и маржу с ретраями. |
| Meshy выкинут | **Устарело 2026-08-27:** Meshy **на FAL** (`fal-ai/meshy/v6/image-to-3d`) можно wrap. Ключ meshy.ai — по-прежнему нет. |

**Не упомянуто в ТЗ, но легальнее Tripo без письма:** Hitem3D API. ToS §3.4(a) прямо: API-юзер может встроить сервис и пускать End Users. Для печати ближе к брифу AI_MESH.

### Юнит-экономика (таблица сломана)

Наши замеры, не ТЗ:

- T2 **warm** preview ~**$0.02–0.03**, Full warm ~**$0.08**; cold в разы дороже. Realistic / 1536 cascade на 24GB+ — бывали **~$0.17–0.30**.
- **$0.006 / меш и 97.6% маржи** — не T2 quality. Фантазия на короткий clay, не прод-рыцарь.
- 10 кредитов × $0.025 = $0.25 за драфт при COGS $0.03–0.10 ещё может быть плюс. Cold / ultra съедают маржу, если нет тарифов **draft / quality / cold**.
- Rodin $0.40 себест. → 36 кредитов / $0.90: тонкая маржа, ретрай убивает.
- Remesh «99.6%» — если бинарь простой. QuadriFlow / Instant Meshes на персонаже T2 часто **не** даёт game-ready квады.
- PBR bake 4K через ComfyUI **после T2 native PBR** — второй раз печь то, что сеть уже отдала. Имеет смысл как retexture чужого меша, не как обязательный шаг.

Пакет **$24.99 = 1000 кредитов** ок как идея. Номинал $0.025 не спасает, если COGS занижен в 5–40 раз.

### Архитектура vs реальный стек

ТЗ рисует greenfield. Факт:

- GPU: этот репо (`worker_trellis2.py`, Hi3DGen, R2).
- Оркестратор POC: FastAPI в `scripts/studio_api.py`.
- Фронт: **AI_MESH**, не `/frontend` здесь.
- T2 уже гоняет **xatlas** в vendored TRELLIS postprocess — «добавить xatlas» не новый ров.
- Ремеш-ручки на T2 уже есть; G1 / pymeshlab — не C++ с нуля в спринте 2.

Новый монорепо в paradox_worker = второй сайт и второй биллинг рядом с живым стеком.

### C++ конвейер как спринт 2

Имеет смысл **позже**, как платная кнопка «упростить сетку / LOD / STL» на GLB с R2 (как dashboard-tools у 3daistudio).  
Не как обязательный шлюз после каждой генерации: T2 quality **не** гонять через QEM 15k, если цель — принятый рыцарь.

Instant Meshes / часть ремешеров — лицензии не «просто MIT». Сначала Python (pymeshlab / уже есть скрипты). C++ — если упрёмся в скорость.

### Стек ТЗ vs наш

| В ТЗ | У нас | Куда класть |
|------|--------|-------------|
| FastAPI + Redis + Postgres + Stripe | `studio_api` POC, без кошелька | Кошелёк и Stripe — **AI_MESH** |
| React 19 / R3F | AI_MESH Studio + lab viewer | Не плодить SPA в worker-репо |
| Celery → C++ после GLB | RunPod async + poll | Очередь уже у GPU-провайдера |
| Prisma | нет | Не тащить до прод-биллинга |

---

## Исправленная схема (когда скажете «делать»)

```
AI_MESH Studio
    │
    ▼
studio_api / бэкенд AI_MESH  ──► кошелёк кредитов (AI_MESH)
    │
    ├── RunPod TRELLIS.2     (default quality)
    ├── RunPod Hi3DGen       (draft)
    └── FAL (ключ на сервере): Meshy, Hunyuan geo-gated, Hitem3D, Rodin, Tripo v2.5
    │
    ▼
Cloudflare R2  ──► опционально remesh/LOD  ──► кабинет / viewer
```

Default Generate = **T2**. Draft = Hi3DGen.  
Hitem3D / FAL Rodin / FAL Tripo / **FAL Meshy** — подписанные опции.  
**Hunyuan на FAL** — слот с гео-гейтом EU/UK/KR (сервер 403). Веса Hunyuan — нет.  
Tripo consumer Studio без письма — нет; Tripo **через FAL Partner** — да.

---

## Куда деть спринты ТЗ

1. **Provider interface** — не `/backend/app/providers` с нуля. Расширять `studio_bridge/` + прод-API в AI_MESH. Адаптеры: T2 (есть), Hi3DGen (есть), FAL Meshy / Hunyuan (гео) / Hitem3D / Rodin / Tripo (`gateway.py`).
2. **C++ remesh** — не спринт 2. Сначала платная CPU-доводка в Python на GLB с R2.
3. **Каталог + Stripe + Three.js** — AI_MESH. Viewer уже в lab (`studio_lab.html`, `model_review.html`).

---

## Не делать, пока нет явной просьбы «внедрять исправленный каркас»

- Монорепо `/backend` `/frontend` `/worker_cpp` в paradox_worker
- Hunyuan веса на RunPod
- Ключ meshy.ai / Tripo Studio в Generate (FAL Partner — ок)
- Обязательный C++/ComfyUI PBR после каждого T2
- Безлимитные подписки

Когда скажете «делать» — не ТЗ 5.0, а этот каркас.

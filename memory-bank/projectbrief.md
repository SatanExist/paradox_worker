# paradox_worker — Описание проекта

## Зачем это нужно

Строим интернет-платформу, где пользователи генерируют **3D-модели**, **текстуры** и **анимации** с помощью ИИ. Этот репозиторий — **GPU-воркер**, первый рабочий кусок платформы.

## Этот репо vs вся платформа

| Слой | Репозиторий | Статус |
|------|-------------|--------|
| RunPod Serverless worker (картинка → 3D) | `paradox_worker` (этот репо) | Рабочий MVP |
| Веб-фронт + API-шлюз | Планируется (`AI_MESH` или отдельный репо) | Не начато |
| Текстуры / анимации | Будущие RunPod-воркеры | Не начато |

## MVP (этот репозиторий)

- Принять публичный **URL картинки** через RunPod Serverless
- Запустить **TRELLIS-image-large** (картинка → 3D)
- Вернуть **GLB в base64** в JSON-ответе

## Критерии успеха

- При cold start веса грузятся с network volume (не качаются заново каждый job)
- Тест через `test_req.py` (`/run` + polling) возвращает `status: success` + `model_base64`
- Docker-образ собирается и работает на RunPod с CUDA 11.8

## Вне scope (пока)

- Аккаунты, биллинг, UI загрузки файлов
- Хранение GLB в S3 (MVP отдаёт base64 в ответе)
- Очередь задач на стороне сайта (масштабирование — на RunPod)

## Ссылки

- GitHub: `https://github.com/SatanExist/paradox_worker`
- Модель TRELLIS: `JeffreyXiang/TRELLIS-image-large`
- Тестовая картинка: `https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/T.png` (fox.png — 404)

# Проверка первой версии — 12 сентября 2026

Выполнено в Windows, Python 3.11, с локальными проектными зависимостями.

| Проверка | Результат |
|---|---|
| `uv run pytest -q` | 25 passed |
| `uv run ruff check app evaluation tests` | Passed |
| `uv run ruff format --check app evaluation tests` | Passed |
| `npm.cmd run build` | TypeScript + Vite passed; JS 106.43 kB / gzip 35.29 kB |
| `npm.cmd test` в frontend | 4 Playwright tests passed |
| RAGAS optional dependencies | Импорт четырех метрик и OpenAI/LangChain adapters прошел |
| Docker image `qdrant/qdrant:v1.19.0` | OCI manifest доступен, amd64/arm64 |
| Запуск FastAPI + embedded Qdrant | Успешный lifespan startup на 127.0.0.1:8000 |

Backend-тесты проверяют настоящий embedded Qdrant: named vectors, staged/ready, sparse, match/content filters, RRF, границы соседства, несовместимость версий, семантические границы документов, batch ingestion и отсутствие дубликатов после повторной обработки. API-проверки покрывают сохранение истории и citations, продолжение диалога, incognito, access token, Origin, ошибки загрузки и незавершенные SSE ответы. Проверка media timeline использует doubles FFmpeg/OpenAI и подтверждает согласование пересекающей границу речи с визуальными сегментами и параллельность стадий.

Playwright проверяет desktop/mobile UI, библиотеку и форму загрузки, составление вопроса, SSE, переход по citation, sanitization Markdown и флаг incognito в запросе. Browser API responses перехвачены тестом: эти сценарии не проверяют реальные модели. Скриншоты визуально просмотрены; горизонтального переполнения при 390px не обнаружено.

Не запускались: оплачиваемые OpenAI inference/embeddings/Whisper/vision/audio вызовы, оценка RAGAS на реальном corpus, обработка настоящего видео через FFmpeg и полный Docker Compose build/run. Ключ и материалы не предоставлены; FFmpeg отсутствует в PATH, Docker Engine не запущен. Поэтому здесь нет заявления о достигнутом качестве спортивного анализа или производительности ingestion на полном матче.

Синтетический evaluation corpus предназначен для первого сравнения конфигураций, не для доказательства экспертного уровня. Следующий измеримый шаг — загрузить один реальный матч, разметить 20–50 вопросов и эпизодов, запустить retrieval/RAGAS harness и отдельно проверить визуальные и причинные выводы человеком.

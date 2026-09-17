Нужно построить RAG-систему для видео, аудио и различных текстовых документов с reranker и query expansion.

В качестве основной vector database необходимо использовать **Qdrant**.

Архитектура retrieval должна быть построена вокруг единой сущности — временного или логического сегмента контента (`segment_id`), а не вокруг отдельных независимых баз для video, audio и text.

Основной контент должен разбиваться на логические и временные сегменты. Каждый сегмент должен иметь единый идентификатор и metadata:

* `content_id`
* `segment_id`
* `content_type`
* `start_time`
* `end_time`
* `transcript`
* `visual_description`
* `audio_description`
* `source`
* `match_id`
* `teams`
* `players`
* другие спортивные metadata

## Архитектура Qdrant

Необходимо использовать одну основную Qdrant collection, например:

`content_segments`

Каждый point должен представлять отдельный segment.

Внутри одного point необходимо использовать несколько представлений одного и того же сегмента.

Пример логической структуры:

`segment`

* dense vector
* sparse vector
* metadata/payload
* transcript
* visual description
* audio description
* timestamp
* source information

Для dense semantic retrieval необходимо использовать embeddings от OpenAI.

Для sparse retrieval необходимо использовать sparse vectors / lexical retrieval в Qdrant.

Sparse retrieval должен дополнять dense embeddings и использоваться прежде всего для точного поиска:

* имен игроков;
* фамилий;
* названий команд;
* номеров игроков;
* счета;
* минут матча;
* терминов;
* конкретных фраз;
* статистических значений;
* названий турниров;
* редких спортивных терминов;
* идентификаторов и других exact-match данных.

Dense и sparse retrieval должны работать совместно.

Базовая схема поиска:

`query`

→ OpenAI dense embedding

→ sparse representation

→ dense retrieval в Qdrant

*

→ sparse retrieval в Qdrant

→ fusion

→ reranker

→ neighboring segment expansion

→ LLM

Для объединения dense и sparse результатов желательно использовать Reciprocal Rank Fusion или аналогичный rank-fusion механизм.

Не следует напрямую складывать raw similarity scores dense и sparse search без нормализации.

## Dense embeddings

Все основные semantic embeddings необходимо создавать с помощью выбранной OpenAI embedding-модели.

Это позволит привести текстовые представления различных модальностей к одному semantic embedding space.

Для текстовых документов:

`document`

→ semantic chunking

→ OpenAI embeddings

→ Qdrant dense vector

*

→ sparse representation

→ Qdrant sparse vector

Для речи внутри видео и аудио:

`video/audio`

→ extract audio

→ Whisper

→ transcript

→ OpenAI embeddings

→ Qdrant dense vector

*

→ sparse representation transcript

→ Qdrant sparse vector

Для видео:

`video`

→ scene / temporal segmentation

→ multimodal visual analysis

→ detailed textual description

→ OpenAI embedding

→ Qdrant

Visual description должен описывать не просто общую сцену, а максимально полезную информацию для спортивного анализа.

Необходимо извлекать:

* игроков;
* игровые действия;
* движение мяча;
* расположение игроков;
* направление атаки;
* прессинг;
* построение команды;
* переходы между фазами игры;
* свободные зоны;
* ошибки позиционирования;
* действия защитников;
* действия голкипера;
* удары;
* передачи;
* перехваты;
* единоборства;
* стандартные положения;
* счет;
* игровые события;
* судейские события;
* другие визуально наблюдаемые детали.

Для non-speech audio при необходимости формировать textual representation звуковых событий.

Например:

* свисток судьи;
* реакция трибун;
* удар по мячу;
* аплодисменты;
* музыка;
* сирена;
* крики;
* другие значимые звуковые события.

Схема:

`audio segment`

→ audio/event analysis

→ textual description

→ OpenAI embedding

→ Qdrant dense vector

При необходимости textual audio description также должен индексироваться sparse retrieval.

## Qdrant point

Желательная логическая структура одного сегмента:

`Point`

* `id`: segment ID

Dense vectors:

* `semantic`

При необходимости архитектура должна позволять позднее добавить дополнительные named vectors:

* `semantic`
* `visual`
* `audio`

Однако в первой версии предпочтительно использовать единое OpenAI semantic embedding space для transcript, visual descriptions, audio descriptions и документов.

Sparse vectors:

* `lexical`

Payload:

* `content_id`
* `segment_id`
* `content_type`
* `match_id`
* `start_time`
* `end_time`
* `transcript`
* `visual_description`
* `audio_description`
* `teams`
* `players`
* `competition`
* `season`
* `source`
* `source_url`
* другие metadata

Все representations одного момента матча должны быть связаны через `segment_id`, `content_id` и timestamps.

## Hybrid retrieval

Поиск должен использовать hybrid retrieval:

`Dense semantic retrieval + Sparse lexical retrieval`

Это важно, потому что dense retrieval лучше понимает смысл запроса, а sparse retrieval лучше работает с точными именами, цифрами и специфическими спортивными терминами.

Например запрос:

«Почему Мбаппе не получил передачу перед вторым голом?»

Dense retrieval должен находить:

* эпизод атаки;
* позиционирование;
* движение игрока;
* контекст перед голом.

Sparse retrieval должен дополнительно усиливать совпадения по:

* `Mbappé`;
* названию команды;
* второму голу;
* конкретным минутам;
* статистике;
* другим exact-match данным.

После этого dense и sparse результаты должны объединяться через fusion.

## Multimodal retrieval

Необходимо обеспечить возможность retrieval по нескольким representations одного спортивного эпизода.

Например пользователь спрашивает:

«Почему команда пропустила второй гол?»

Query expansion может сформировать несколько специализированных запросов:

* эпизод непосредственно перед вторым голом;
* потеря мяча;
* позиционирование защитников;
* движение атакующей команды;
* действия центральных защитников;
* действия голкипера;
* свободное пространство между линиями;
* ошибка при переходе из атаки в оборону.

Каждый expanded query должен проходить hybrid retrieval.

Результаты затем необходимо объединять и передавать reranker.

Общий pipeline:

`User query`

→ query understanding

→ query expansion

→ query decomposition

→ OpenAI dense embeddings

*

→ sparse query representation

→ parallel hybrid retrieval

→ Reciprocal Rank Fusion

→ reranker

→ neighboring segment expansion

→ context construction

→ LLM

## Query routing

Query expansion желательно дополнить query routing.

Система должна определять, какая информация наиболее важна для конкретного вопроса.

Например:

«Что тренер сказал после матча?»

Основной вес:

* transcript;
* documents;
* sparse text.

Запрос:

«Почему левый защитник не успел перекрыть зону перед голом?»

Основной вес:

* visual descriptions;
* соседние video segments;
* tactical context.

Запрос:

«Когда судья дал свисток перед пенальти?»

Основной вес:

* transcript;
* audio events;
* visual event;
* timestamps.

## Neighboring segment expansion

После обнаружения релевантного сегмента необходимо автоматически получать соседние временные сегменты.

Например:

`previous segment`

*

`matched segment`

*

`next segment`

Это необходимо, потому что причина спортивного события очень часто находится не в самом найденном моменте, а за несколько секунд до него.

Например гол произошел на `63:18`, но ошибка могла начаться на `62:55`.

Поэтому RAG не должен анализировать эпизоды изолированно.

Для важных игровых моментов желательно иметь возможность динамически расширять temporal context.

Например:

`hit timestamp ± 15–30 seconds`

или до ближайшей логической границы игрового эпизода.

## Reranker

После hybrid retrieval и fusion необходимо использовать reranker.

Pipeline:

`dense top-K`

*

`sparse top-K`

→ fusion

→ candidate segments

→ reranker

→ top relevant segments

Reranker должен учитывать:

* запрос пользователя;
* transcript;
* visual description;
* audio description;
* temporal context;
* metadata;
* соседние эпизоды.

Важно оптимизировать pipeline так, чтобы дорогой reranker применялся только к небольшому количеству кандидатов.

Например:

`Dense top-30`

*

`Sparse top-30`

→ RRF

→ top-20

→ reranker

→ top-5 / top-8

→ neighbor expansion

→ LLM

## Ingestion pipeline

Загрузка контента должна быть максимально быстрой.

Необходимо использовать асинхронную и batch-oriented архитектуру ingestion.

Для видео:

1. принять файл;
2. определить сцены / временные сегменты;
3. извлечь audio track;
4. выполнить Whisper transcription;
5. параллельно выполнить visual analysis;
6. определить значимые audio events;
7. сформировать semantic chunks;
8. сформировать visual descriptions;
9. сформировать audio descriptions;
10. batch-генерация OpenAI embeddings;
11. batch-генерация sparse representations;
12. batch-upsert points в Qdrant.

Не выполнять OpenAI embedding API request отдельно для каждого маленького chunk, если можно отправить несколько chunks batch-запросом.

Qdrant upsert также необходимо выполнять batch-операциями.

Pipeline должен быть максимально параллельным там, где этапы не зависят друг от друга.

Например:

`video upload`

→

параллельно:

* ASR;
* scene detection;
* visual analysis;
* audio event detection.

После этого результаты объединяются по timeline.

## Основная единица хранения

Основной единицей retrieval должен быть не файл и не целое видео, а `segment`.

Например:

`match_123`

`segment_001`

`00:15:20–00:15:32`

содержит:

* transcript;
* visual description;
* audio events;
* dense vector;
* sparse vector;
* metadata.

Это позволяет привязать ответ непосредственно к конкретному моменту матча.

## Спортивный аналитик

Мне нужен экспертный спортивный аналитик, который умеет качественно анализировать и объяснять каждый момент матча.

Он не должен просто пересказывать найденный transcript.

Аналитик должен связывать:

* визуальные действия игроков;
* расположение игроков;
* тактическую структуру;
* действия до события;
* действия после события;
* движение мяча;
* статистические данные;
* transcript;
* документы;
* предыдущие игровые эпизоды;
* последующие игровые эпизоды.

Ответ должен объяснять причинно-следственную связь.

Например вместо:

«Команда пропустила после передачи с фланга.»

Ответ должен анализировать:

* где возникло свободное пространство;
* кто потерял позицию;
* как двигалась линия защиты;
* кто должен был страховать;
* почему прессинг не сработал;
* какое действие создало преимущество;
* была ли ошибка индивидуальной или структурной;
* что могло быть сделано иначе.

Аналитик должен четко разделять:

* факты, непосредственно наблюдаемые в источниках;
* выводы на основе этих фактов;
* предположения, если информации недостаточно.

## RAGAS

В качестве системы оценки качества RAG необходимо добавить RAGAS.

Необходимо оценивать как минимум:

* faithfulness;
* answer relevancy;
* context precision;
* context recall.

Также необходимо создать собственный evaluation dataset для спортивного RAG.

Dataset должен содержать различные категории вопросов:

* фактологические;
* temporal;
* tactical;
* visual;
* statistical;
* causal;
* multi-hop;
* вопросы по конкретному игроку;
* вопросы по игровому эпизоду;
* вопросы, требующие нескольких источников.

Отдельно желательно оценивать качество retrieval до LLM.

Например:

* Recall@K;
* Precision@K;
* MRR;
* NDCG;
* Hit Rate.

Также необходимо отдельно оценивать:

* dense retrieval;
* sparse retrieval;
* hybrid retrieval;
* hybrid + reranker.

Это позволит объективно проверить, дает ли sparse retrieval реальное улучшение.

## Frontend

Frontend должен быть современным, очень красивым и по функциональности напоминать ChatGPT.

Необходимо реализовать:

* обычные чаты;
* режим инкогнито без сохранения истории;
* историю чатов;
* историю диалогов;
* streaming ответов;
* markdown;
* отображение источников;
* отображение использованных документов;
* ссылки на конкретные видео;
* timestamps найденных игровых эпизодов;
* возможность перейти непосредственно к соответствующему моменту матча;
* удобное отображение найденных сегментов;
* возможность посмотреть контекст до и после найденного события.

Для спортивных ответов желательно показывать citations примерно в формате:

`Матч → тайм → timestamp → источник`

Например:

`Real Madrid vs Barcelona — 2nd half — 63:18`

При клике пользователь должен переходить непосредственно к соответствующему моменту видео.

Итоговая архитектура retrieval должна выглядеть примерно так:

`Documents / Video / Audio`

→ preprocessing

→ temporal / semantic segmentation

→ Whisper + multimodal analysis

→ textual representations

→ OpenAI dense embeddings

*

→ sparse representations

→ Qdrant

→ dense retrieval + sparse retrieval

→ RRF / hybrid fusion

→ reranker

→ neighboring segment expansion

→ sports context builder

→ expert sports analyst LLM

→ answer with timestamps and citations.

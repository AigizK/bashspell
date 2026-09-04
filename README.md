# Bashspell

## Быстрая проверка словаря из CLI

В репозитории есть исполняемый файл `./bashspell`. По умолчанию он сам выбирает
самую новую датированную папку с `bash.aff` и `bash.dic` из `static/hunspell`.
Сейчас это `28.01.2024`.

```bash
# Короткая форма проверки слов
./bashspell башҡорт башҡорттар башкорд

# Проверка текста (текст также можно передать через stdin)
./bashspell text 'Мин башҡортса яҙам.'
cat article.txt | ./bashspell text
./bashspell file article.txt

# Интерактивный режим
./bashspell repl

# Инструменты для отладки правил
./bashspell analyze башҡорттар  # морфологический разбор Hunspell
./bashspell stem башҡорттар     # возможные основы
./bashspell entry башҡорт       # точная статья и её номер в bash.dic
./bashspell rule N15            # весь блок SFX/PFX для флага
./bashspell validate            # структура, флаги, условия, окончания, морфотеги и загрузка
```

Для быстрой регрессионной проверки новых правил можно одновременно указать
формы, которые должны приниматься и отклоняться:

```bash
./bashspell test \
  --valid башҡорт башҡорттар \
  --invalid башкорд
```

Большой набор тест-кейсов удобно хранить в UTF-8 файле:

```text
# Комментарий
+ башҡорт
+ башҡорттар
- башкорд
```

```bash
./bashspell test --file my-rules.txt
```

Для версии `28.01.2024` собран регрессионный набор из 285 нормативных и
ошибочных форм по справочной грамматике и найденным дефектам словаря. После
исправлений команда завершается с кодом `0`:

```bash
./bashspell --dict 28.01.2024 test \
  --file tests/data/grammar-regressions-28.01.2024.txt
```

Отдельный набор фиксирует совместимость с исправлениями морфофонологии из
`apertium-bak` PR [#4](https://github.com/apertium/apertium-bak/pull/4) и
[#5](https://github.com/apertium/apertium-bak/pull/5):

```bash
./bashspell test --file tests/data/apertium-pr-4-5-regressions.txt
```

У всех проверок exit code равен `0`, если ошибок или несовпадений нет, `1` —
если они есть, `2` — при ошибке запуска. Для автоматизации доступен `--json`:

```bash
./bashspell --json text 'Мин башҡортса яҙам.'
```

Другую версию словаря можно выбрать по имени или пути:

```bash
./bashspell --dict 28.01.2024 check башҡорт
./bashspell --dict /path/to/dictionary/bash check башҡорт
```

CLI использует системный бинарник `hunspell`; Python-пакеты ему не нужны.

```bash
# macOS
brew install hunspell

# Ubuntu / Debian
sudo apt-get install hunspell
```

Путь к нестандартному бинарнику можно передать через `--hunspell` или переменную
окружения `HUNSPELL`.

## Запуск веб-приложения

```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Для сборки Python-биндинга Hunspell в Ubuntu дополнительно могут понадобиться:

```bash
sudo apt-get install python3.10-dev libhunspell-dev hunspell
```

## Справочные правила

Офлайн-копии академической и алгоритмической грамматик находятся в
[`docs/grammar-reference`](docs/grammar-reference/README.md). Зеркало содержит
452 доступные HTML-страницы, а `manifest.json` фиксирует исходные URL, размеры и
SHA-256 файлов. Для повторной загрузки используется
`python3 tools/download_grammar_reference.py`.

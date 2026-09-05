import sqlite3
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import List

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from bashspell_text import should_ignore_word
from bashspell_morphology import AnalysisLimitError, Morphology
from bashspell_morphology_labels import legend_for

ACTUAL_BASH_HUNSPELL_VERSION = "28.01.2024"

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

try:
    import hunspell

    hobj = hunspell.HunSpell(
        f'static/hunspell/{ACTUAL_BASH_HUNSPELL_VERSION}/bash.dic',
        f'static/hunspell/{ACTUAL_BASH_HUNSPELL_VERSION}/bash.aff')
except ImportError:
    hobj = None


class CandidatesBatch(BaseModel):
    unverified_words: List[str]
    include_suggestions: bool = True


class SuggestionRequest(BaseModel):
    word: str


class MorphologyRequest(BaseModel):
    word: str = Field(min_length=1, max_length=256)


morphology_lock = RLock()


@lru_cache(maxsize=1)
def get_morphology():
    return Morphology(Path(__file__).resolve().parent / 'static' / 'hunspell' / ACTUAL_BASH_HUNSPELL_VERSION)


# The dictionary is shared by worker threads; pyhunspell does not promise that
# concurrent calls on one instance are safe. Cache lookups take the same lock
# so simultaneous requests for a word do not repeat an expensive suggestion.
hunspell_lock = RLock()


@lru_cache(maxsize=20000)
def is_correct(word):
    return should_ignore_word(word) or hobj.spell(word)


@lru_cache(maxsize=2000)
def suggestions(word):
    return tuple(hobj.suggest(word)) if not is_correct(word) else ()


def require_hunspell():
    if hobj is None:
        raise HTTPException(status_code=503, detail="Spellchecker is unavailable")


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def cleanup(item:str):
    item=item.lstrip("—")
    return item

def spellChecker(unverified_words, include_suggestions=True):
    require_hunspell()
    correct = []
    for original in unverified_words:
        word = cleanup(original)
        with hunspell_lock:
            valid = is_correct(word)
            variants = list(suggestions(word)) if include_suggestions and not valid else []
        correct.append({'word': original, 'correct': valid, 'variants': variants})
    return correct


def save_to_sqlite_db(data, version):
    # Подключение к базе данных (если базы данных нет, она будет создана)
    conn = sqlite3.connect('text.db')
    cursor = conn.cursor()

    # Создание таблицы, если она еще не существует
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS words (
        word TEXT,
        version TEXT,
        count_of_variants INTEGER,
        PRIMARY KEY (word, version)
    )
    ''')

    # Добавление данных в таблицу
    for item in data:
        word = item['word']
        count_of_variants = len(item['variants'])
        cursor.execute(
            'INSERT OR REPLACE INTO words (word, version, count_of_variants) VALUES (?, ?, ?)',
            (word, version, count_of_variants))

    # Фиксация изменений и закрытие соединения
    conn.commit()
    conn.close()


@app.post("/data_processing")
def data_processing(data: CandidatesBatch, background_tasks: BackgroundTasks):
    correct = spellChecker(data.unverified_words, data.include_suggestions)
    # Keep the legacy API and its statistics. The fast path does not calculate
    # variant counts, and must not overwrite those counts with invented zeros.
    if data.include_suggestions:
        background_tasks.add_task(save_to_sqlite_db, correct, ACTUAL_BASH_HUNSPELL_VERSION)
    return {'message': correct}


@app.post("/suggestions")
def word_suggestions(data: SuggestionRequest, background_tasks: BackgroundTasks):
    correct = spellChecker([data.word])
    background_tasks.add_task(save_to_sqlite_db, correct, ACTUAL_BASH_HUNSPELL_VERSION)
    return correct[0]


@app.post("/analyze")
def analyze_word(data: MorphologyRequest):
    word = unicodedata.normalize('NFC', data.word.strip())
    if not re.fullmatch(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", word):
        raise HTTPException(status_code=422, detail="Enter one word")
    with morphology_lock:
        analyzer = get_morphology()
    try:
        result = analyzer.analyze(word)
    except AnalysisLimitError:
        raise HTTPException(status_code=503, detail="Complete analysis could not be finished")
    return {**result, 'legend': legend_for(result['analyses'])}

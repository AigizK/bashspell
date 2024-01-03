import sqlite3
from typing import List

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse

ACTUAL_BASH_HUNSPELL_VERSION = "03.01.2024"

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


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def cleanup(item:str):
    item=item.lstrip("—")
    return item

def spellChecker(unverified_words):
    correct = []
    for i in range(len(unverified_words)):
        word = unverified_words[i]
        word = cleanup(word)
        if not hobj.spell(word):
            correct.append({'word': unverified_words[i],
                            'variants': hobj.suggest(word)})
        else:
            correct.append({'word': unverified_words[i], 'variants': []})
    return correct


def spellChecker_notHunspell(unverified_words):
    correct = []
    for i in range(len(unverified_words)):
        if len(unverified_words[i]) <= 3:
            correct.append({'word': unverified_words[i],
                            'variants': [unverified_words[i], 'вариант1',
                                         'вариант2', 'вариант3']})
        else:
            correct.append({'word': unverified_words[i], 'variants': []})
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
async def data_processing(data: CandidatesBatch):
    try:
        correct = spellChecker(data.unverified_words)
    except:
        correct = spellChecker_notHunspell(data.unverified_words)

    save_to_sqlite_db(correct, ACTUAL_BASH_HUNSPELL_VERSION)
    return {'message': correct}

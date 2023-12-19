- Установите virtual env: `python3.10 -m venv venv`
- Активируйте: `source venv/bin/activate`
- Установите зависимости: `pip install -r requirements.txt`
- Запустите сайт: `uvicorn main:app --reload`

Чтоб установить Hunspell в Ubuntu, надо поставить эти библиотеки сперва:
1. sudo apt-get install python3.10-dev
2. sudo apt-get install libhunspell-dev
3. sudo apt-get install hunspell

# Orders API

A small ordering API built with Python and FastAPI: accounts, products,
orders and payments. Built step by step, with a lesson for each step in
`docs/`.

## Run it

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive documentation.

## Lessons

1. [A first API that runs](docs/lesson-01-hello-api.md)

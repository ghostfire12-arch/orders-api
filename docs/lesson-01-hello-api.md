# Lesson 1: A first API that runs

## What is an API?

An API is a program that other programs talk to over the web. A client (a
browser, a phone app, another server) sends a **request** to an address, and
the API sends back a **response**, usually as JSON.

A request has a **method** and a **path**:

| Method | Means            | Example                     |
| ------ | ---------------- | --------------------------- |
| GET    | read something   | `GET /products`             |
| POST   | create something | `POST /orders`              |
| PUT    | replace          | `PUT /products/3`           |
| DELETE | remove           | `DELETE /products/3`        |

## The tools we use

- **Python**: the language.
- **FastAPI**: a library that turns Python functions into web endpoints and
  generates documentation for them.
- **Uvicorn**: the server program that listens for requests and hands them to
  FastAPI. FastAPI is the app, Uvicorn runs it.
- **Virtual environment (`.venv`)**: a private folder of packages for this
  project only, so projects never fight over versions.

## The project layout

```
orders-api/
  app/
    __init__.py     marks "app" as a Python package (can be empty)
    main.py         the application and its routes
  requirements.txt  exact package versions, so anyone can recreate the setup
  .gitignore        files git must never upload (secrets, .venv)
  docs/             these lessons
```

## Reading `app/main.py`

1. `app = FastAPI(...)` creates the application.
2. `@app.get("/")` says "run the next function for GET requests to `/`".
3. The function returns a Python dictionary. FastAPI converts it to JSON.
4. `/health` is a convention: hosting platforms call it to check the service.

## Running it

From the `orders-api` folder:

```
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- `app.main:app` means "in the file `app/main.py`, use the object named `app`".
- `--reload` restarts the server when you save a file (development only).

Then open:

- http://127.0.0.1:8000/ for the JSON response
- http://127.0.0.1:8000/docs for interactive documentation you can click
  through. FastAPI builds this automatically from your code.

## Why `--only-binary` when installing?

`pip install --only-binary=:all:` refuses to run a package's build script.
Install scripts can run any code on your computer, so skipping them removes a
common way malicious packages attack developers.

## Try it yourself

1. Add a route `GET /about` that returns your name and the API version.
2. Open `/docs` and call it from the page.

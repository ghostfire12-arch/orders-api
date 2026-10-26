# Lesson 4: Accounts, password hashing and login

Until now anyone could create products. Real APIs need to know **who** is
calling and **what they may do**. This lesson adds accounts and login, and it
is the most security-sensitive part of the project, so we go slowly.

Two words you must keep apart:

- **Authentication**: proving who you are ("log in").
- **Authorization**: deciding what you are allowed to do ("admins only").

## The golden rule: never store passwords

If your database leaks and it contains passwords, every user is compromised,
including on other sites where they reused the password. So we never keep the
password. We keep a **hash**.

A hash is a one-way scramble: easy to make from a password, practically
impossible to turn back. To check a login, we hash what the person typed and
compare it to the stored hash.

### Why not just use SHA-256 or MD5?

They are designed to be *fast*. An attacker with a stolen database can try
billions of guesses per second. Password hashes must be *slow on purpose*.
We use **Argon2id**, the algorithm currently recommended for passwords. It is
slow and needs a lot of memory, which makes mass guessing expensive.

### Salt

`hash_password("abc")` gives a different result every time. A random **salt**
is mixed in and stored inside the hash string. Two users with the same
password get different hashes, so an attacker cannot crack one and get many.

Look at a stored hash:

```
$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
```

It also stores the settings (`m`, `t`, `p`), so old hashes keep working if we
make the settings stronger later.

## Step 1: The users table (`app/models.py`)

```python
class UserRow(Base):
    email: ...  unique=True, index=True
    password_hash: ...
    is_admin: ...  default False
```

`unique=True` makes the **database** refuse a second account with the same
email, even if two registrations arrive at the same instant. Checking in
Python first is not enough on its own, because two requests can both pass the
check. The database rule is the real guard, and the repository turns its
error into `EmailAlreadyRegistered`.

## Step 2: Shapes of data (`app/schemas.py`)

| Model         | Used for              | Notes                                     |
| ------------- | --------------------- | ----------------------------------------- |
| `UserCreate`  | registering           | password 8 to 128 characters              |
| `LoginRequest`| logging in            | max length so nobody sends a huge string  |
| `UserPublic`  | what we send back     | **no password, no hash**                  |
| `Token`       | login response        | the token and its type                    |

Two details worth studying:

- **`UserPublic` is a safety net.** Routes declare `response_model=UserPublic`,
  so even if you accidentally return a whole database row, FastAPI only sends
  the fields in that model. The hash cannot leak.
- **The 128 maximum.** Hashing is slow. Without a limit, an attacker could
  send a megabyte-long "password" to make your server burn time.

### A bug the tests found

The email validator lowercases and trims the email. At first it ran *after*
the pattern check, so `"  Ada@Example.COM "` (with spaces) was rejected before
it could be cleaned. The fix was `mode="before"`, which runs the cleanup
first. Order of validation steps matters, and tests are how you find this.

## Step 3: Tokens (`app/security.py`)

After login the server cannot ask for the password on every request. Instead it
gives the client a **token**, a signed note saying "this is user 7, valid
until 3:30 pm". The client sends it back with each request.

We use a **JWT** (JSON Web Token). It has three parts separated by dots:

```
header . payload . signature
eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiIxIiwiZXhwIjoxNz... . kJ3x...
```

- The **payload** holds claims: `sub` (subject, the user id), `iat` (issued at),
  `exp` (expires).
- The **signature** is made with our secret key. Change one character of the
  payload and the signature no longer matches.

Important: the payload is **readable by anyone**. It is signed, not
encrypted. Never put secrets in a token.

### The secret key (`app/config.py`)

Anyone who knows the key can forge a token for any user, including an admin.
So it is read from an environment variable, never written in code, never
committed. If it is missing in development, a random one is made at startup
(and logins reset on each restart). For a stable key:

```
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:SECRET_KEY = "paste-the-output-here"
```

See `.env.example`. Never commit a real `.env` file (it is in `.gitignore`).

### Verifying safely

```python
jwt.decode(token, SECRET_KEY,
           algorithms=[JWT_ALGORITHM],
           options={"require": ["exp", "sub"]})
```

- `algorithms=[...]` pins the algorithm. A token's header can claim any
  algorithm, including `"none"` (no signature at all). If the server trusted
  the header, an attacker could forge tokens with no key. Our test
  `test_none_algorithm_attack_is_rejected` proves we are safe.
- `require` rejects tokens that have no expiry.
- Tokens last 30 minutes by default, to limit damage if one is stolen.

## Step 4: The routes (`app/routers/auth.py`)

| Request              | What it does                                   |
| -------------------- | ---------------------------------------------- |
| `POST /auth/register`| create an account (201, or 409 if email taken)|
| `POST /auth/login`   | exchange email and password for a token        |
| `GET /users/me`      | show the logged-in user (needs a token)        |

Security choices inside `login`:

1. **One error message for both failures.** "Incorrect email or password" is
   returned whether the email is unknown or the password is wrong. A more
   helpful message would let an attacker find out which emails have accounts.
2. **Equal timing.** If the email is unknown, we still run a hash check against
   a dummy hash. Otherwise unknown emails would answer instantly and real ones
   slowly, which leaks the same information through timing.
3. `is_admin` sent by a client at registration is ignored. Our test
   `test_users_cannot_make_themselves_admin` checks it.

## Step 5: Who is calling? (`app/deps.py`)

`get_current_user` is a dependency, like `get_db` in lesson 3. A route that
lists `user: CurrentUser` gets the logged-in user, or the request is stopped
with **401** before your function runs. `require_admin` adds a second check.

| Code | Meaning                                         |
| ---- | ----------------------------------------------- |
| 401  | we do not know who you are (no or bad token)    |
| 403  | we know who you are, and you are not allowed    |

`POST /products` now needs an admin. `GET /products` stays public.

## Step 6: Creating the first admin (`app/create_admin.py`)

How does the first admin get made? Not through the API. Anyone on the internet
can call a route, so a "make me admin" route would be a hole. Instead, a
script that only someone with access to this computer can run:

```
.venv\Scripts\python.exe -m app.create_admin
```

It asks for an email and a password (typed hidden, using `getpass`, so it is
not shown or saved in your terminal history). For an existing user it only
promotes them and never touches their password.

## Try the whole flow in /docs

1. Start the server and open `/docs`.
2. `POST /auth/register`, then `POST /auth/login`. Copy the `access_token`.
3. Click the green **Authorize** button, paste the token, and call
   `GET /users/me`.
4. Try `POST /products`. You get **403**: you are logged in but not an admin.
5. Run `create_admin` for your email, log in again, and `POST /products`
   works (**201**).

## Run the tests

```
.venv\Scripts\python.exe -m pytest -q
```

You should see all tests pass. (In lesson 4 the suite had 50 tests. It took
about 15 seconds because Argon2 is slow by design. Lesson 5 makes it faster.)

## What we skipped on purpose (real systems need these)

- **Rate limiting.** Nothing stops someone trying thousands of passwords.
  Production APIs limit login attempts per account and per IP address.
- **HTTPS.** Tokens and passwords travel in plain text over `http`. A real
  deployment must use HTTPS only.
- **Logout and refresh tokens.** A JWT cannot be cancelled before it expires.
  Larger systems use short tokens plus refresh tokens.
- **Email verification and password reset.**
- **Stronger password rules**, such as rejecting common passwords.

## Try it yourself

1. Change `ACCESS_TOKEN_MINUTES` to `1` (as an environment variable), log in,
   wait two minutes, and call `/users/me`. What do you get?
2. Copy the middle part of your token and paste it into a Base64 decoder.
   Read your own payload. This is why secrets never go in a token.
3. Add a test that registers two users and checks that one cannot see the
   other's data. (We will need this once orders exist.)

## Words to remember

**Authentication / authorization**: who you are vs what you may do. **Hash**:
a one-way scramble. **Salt**: random data that makes each hash unique.
**Argon2id**: a slow, memory-hungry password hash. **JWT**: a signed token.
**Claim**: one fact inside a token. **401 / 403**: not identified / not
allowed. **Environment variable**: a setting kept outside your code.

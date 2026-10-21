# Chatly — WhatsApp-style real-time chat (Django 6.1)

- Public **landing page** at `/` for visitors (what Chatly is, free limits, packs, sign up / log in)
- **Free daily limits** per user (default 20 text, 5 voice, 5 photos) and **paid message packs** (Razorpay)
- Sign up / log in with **phone number or email + password**
- Home page with your personal **invite link** (copy button, native share on phones)
- Opening an invite link → new people create an account, existing people just log in → both are **connected automatically** and land in the chat
- **Real-time 1-to-1 chat** (Django Channels + websockets): live messages, typing indicator, unread badges, read ticks (✓ / ✓✓ blue), chat search, load-earlier-messages, auto-reconnect, dark mode, phone layout
- Ready for **Render** (free plan): Postgres, WhiteNoise static files, Daphne ASGI server

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Open http://127.0.0.1:8000/ . To try the invite flow, sign up, copy your link from the home page, then open it in a private/incognito window (a second browser session) and sign up as a second user.

Run the tests: `python manage.py test`

## Free limits & buying more messages

Everything is configured in one place: **`config/settings.py` → "FREE LIMITS & PAID PACKS"** (or with env vars).

```python
FREE_DAILY_LIMITS = {"text": 20, "voice": 5, "image": 5}   # env: FREE_TEXT_PER_DAY, FREE_VOICE_PER_DAY, FREE_IMAGES_PER_DAY
LIMITS_TIMEZONE = "UTC"                                     # free counters reset at midnight in this timezone
CREDIT_PACKS = [{"id": "starter", "name": "Starter", "price": 49, "text": 200, "voice": 20, "image": 20}, ...]
```

Change a number and restart: the chat, the landing page, the home page and the buy page all follow it.

- Free messages are used first; bought messages are used only when the free ones for the day are gone, and they never expire.
- Text is checked in `chat/consumers.py`, photos and voice in `chat/views.py` (`attach_api`); the rules live in `billing/limits.py`.
- Give someone free messages from `/admin/` -> Billing -> Wallets. Payments appear under Orders.

### Payments (Razorpay)

1. Create a Razorpay account and copy the **Key ID** and **Key Secret** (use the *test* keys first).
2. Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` (in `.env` locally, or in the Render dashboard).
3. Recommended: in Razorpay -> Webhooks add `https://YOUR-DOMAIN/buy/webhook/` for the events `payment.captured` and `order.paid`, and put its secret in `RAZORPAY_WEBHOOK_SECRET`. This adds the messages even if the buyer closes the tab right after paying.

With `DEBUG=True` and no keys, the Buy button runs a **fake test payment** so you can try the whole flow locally. It is disabled automatically in production.

After pulling these changes run `python manage.py migrate` (adds the `billing` tables).

## Deploy on Render (free)

1. Push this folder to a GitHub repo.
2. In Render: **New + → Blueprint**, pick the repo. `render.yaml` creates the web service and a Postgres database, generates `SECRET_KEY`, and wires `DATABASE_URL`.
3. Wait for the build (`build.sh` installs packages, collects static files, runs migrations). Open the `onrender.com` URL.

Manual setup instead of a Blueprint:

| Setting | Value |
|---|---|
| Runtime | Python |
| Build command | `bash build.sh` |
| Start command | `daphne -b 0.0.0.0 -p $PORT config.asgi:application` |
| Health check path | `/healthz/` |
| Env vars | `SECRET_KEY` (random string), `DEBUG=False`, `DATABASE_URL` (Postgres URL), `PYTHON_VERSION=3.13.5` |

The invite link uses whatever domain the site is served from, so it works on `onrender.com` and on a custom domain with no changes (for a custom domain also set `CSRF_TRUSTED_ORIGINS=https://yourdomain.com`).

### Free-tier things to know

- **Cold starts:** free web services sleep after a period of inactivity. The first visit afterwards takes a while to wake up; open chats reconnect on their own.
- **Database:** Render's free Postgres has had an expiry limit, so check their current free-plan terms. Any Postgres works: create a free one elsewhere (e.g. Neon or Supabase) and paste its connection string into `DATABASE_URL`.
- **One instance only on the free plan:** live messages are routed in memory, which is correct for a single server process. To run several instances, add a Redis instance and set `REDIS_URL` (already supported, `channels-redis` is installed).

## How it works

```
config/            settings, urls, asgi (HTTP + websocket routing)
accounts/          custom User (email / phone / display name / invite_code),
                   login backend, signup/login views, invite flow
chat/              Conversation + Message models, websocket consumer,
                   dashboard + history views
billing/           daily limits, message packs, Razorpay checkout + webhook
templates/, static/  UI (plain HTML/CSS/JS, no build step)
```

- **Phone numbers** are normalised to `+<country><number>`, so `98765 43210`, `09876543210` and `+91 98765-43210` are the same person. Numbers typed without a country code get `DEFAULT_COUNTRY_CODE` (default `91`, change it with an env var).
- **Invite flow:** `/invite/<code>/` remembers the inviter in the session. After signup *or* login, the two users get a conversation, and the inviter's open dashboard updates instantly.
- **Websocket:** one connection per tab at `/ws/chat/`. Each user has a channel-layer group, so one connection drives the chat window, sidebar and badges. Messages carry a client-generated id, so a resend after a dropped connection never creates duplicates.
- Messages are rendered with `textContent` only (HTML in messages is shown as plain text).

## Good next steps

- Send invites by email/SMS (Django email backend, or an SMS provider such as Twilio)
- Rate limiting on login/signup (e.g. `django-axes`)
- Group chats, images/files (needs object storage such as S3/Cloudflare R2 because Render's disk is ephemeral), online/last-seen status, push notifications

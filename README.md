# Muellima 🎓

Una scuola AI personalizzata costruita con Django e OpenAI Realtime API.
Inserisci qualsiasi materia, genera un corso completo e segui lezioni vocali 
interattive con un professore AI.

## Requisiti

- Python 3.10+
- Una chiave API OpenAI valida
- Browser con supporto WebRTC (Chrome, Firefox, Edge — raccomandato Chrome)

## Setup

```bash
# 1. Clona o scarica il progetto
cd muellima

# 2. Crea un virtual environment
python -m venv venv

# 3. Attiva il virtual environment
# Su macOS/Linux:
source venv/bin/activate
# Su Windows:
venv\Scripts\activate

# 4. Installa le dipendenze
pip install -r requirements.txt

# 5. Configura le variabili d'ambiente
cp .env.example .env
# Edita .env e inserisci la tua OPENAI_API_KEY
# Per il login social configura anche le credenziali OAuth Google e/o Facebook.
# Callback locali:
# Google:   http://127.0.0.1:8000/accounts/google/login/callback/
# Facebook: http://127.0.0.1:8000/accounts/facebook/login/callback/

# 6. Crea le migrazioni e applica
python manage.py makemigrations
python manage.py migrate

# 7. Avvia il server
python manage.py runserver
```

## Accesso e pagamenti

Configura Stripe in `.env` con `STRIPE_SECRET_KEY` e `STRIPE_WEBHOOK_SECRET`.
Registra il webhook `/billing/webhook/` per gli eventi:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

`USERS_WHITELIST` accetta email separate da virgola e concede accesso completo.
`MOCK=True` bypassa il paywall in sviluppo e non deve essere usato in produzione.

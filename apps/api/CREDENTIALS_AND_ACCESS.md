# SANAD.AI — Credentials & Access Checklist

## Important security rule

API keys are secrets.

Do NOT:
- paste them into `SPEC.md`;
- commit them to GitHub;
- put them in frontend JavaScript;
- include them in screenshots;
- upload `.env` to public repositories.

Use:
- local `.env` during development;
- server-side secret/environment settings during deployment.

---

## 1. OpenAI API (optional legacy path)

Purpose:
- intent preservation;
- structured claim reconstruction;
- multi-query generation.

Needed:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

This upgrade keeps remote semantic processing disabled by default. The rule-first
and multilingual semantic fallback runs locally and does not require OpenAI.

---

## 2. Brave Search API

Purpose:
- broad discovery;
- restrict discovery to trusted domains such as `sunnah.com`;
- find candidate canonical references when the official source API lacks semantic free-text search.

Needed:
- `BRAVE_SEARCH_API_KEY`

Security:
- server-side only.

Important:
Brave output is discovery evidence only. It is never automatically primary evidence.

---

## 3. Sunnah.com API

Purpose:
- official/structured validation of candidate hadith references.

Needed:
- `SUNNAH_API_KEY`

Important:
- API coverage may be partial;
- if a candidate cannot be confirmed through the official API, SANAD.AI must not silently label it as verified primary evidence.

---

## 4. HadithAPI temporary provider

Purpose:
- structured English/Arabic hadith search before paid web discovery;
- temporary curated-provider metadata while Sunnah.com API access is unavailable.

Needed:
- `HADITH_API_KEY`

Security:
- server-side only;
- HadithAPI requires the key as an `apiKey` query parameter, so complete request URLs must never be logged or reported.

Important:
- HadithAPI is registered as curated secondary / Tier 2;
- successful results may be labeled `VERIFIED_PROVIDER` only;
- `official_api_validated` remains false;
- results cannot become `VERIFIED_DIRECT` or Tier-1 primary evidence without separate Sunnah.com Official API validation;
- the provider does not document a canonical direct-item URL, so SANAD.AI must not construct one.

---

## 5. Quran Foundation

Purpose:
- exact-reference Qur'an retrieval through Content API;
- dynamic semantic search through Search API followed by Content API hydration;
- provider-metadata selection of an Indonesian translation resource.

Needed:
- `QURAN_FOUNDATION_CLIENT_ID`
- `QURAN_FOUNDATION_CLIENT_SECRET`
- `QURAN_FOUNDATION_ENV=prelive|production`

Security and evidence boundary:
- credentials and OAuth access tokens are backend-only;
- tokens are cached by scope (`content` or `search`) and never returned by the API;
- missing credentials produce `Sumber Qur’an belum dapat diakses saat ini.`;
- no verse, translation, or URL may be fabricated as a fallback;
- prelive contains only a limited corpus, so production permission is needed for
  complete surah coverage.

---

## `.env` example

Create a local file named `.env`:

```env
OPENAI_API_KEY=YOUR_PRIVATE_KEY
OPENAI_MODEL=YOUR_MODEL_ID

BRAVE_SEARCH_API_KEY=YOUR_PRIVATE_KEY
HADITH_API_KEY=YOUR_PRIVATE_KEY
SUNNAH_API_KEY=YOUR_PRIVATE_KEY
QURAN_FOUNDATION_CLIENT_ID=YOUR_PRIVATE_CLIENT_ID
QURAN_FOUNDATION_CLIENT_SECRET=YOUR_PRIVATE_CLIENT_SECRET
QURAN_FOUNDATION_ENV=prelive

SANAD_HTTP_TIMEOUT=12
SANAD_MAX_WEB_RESULTS=10
SANAD_HADITH_API_PAGE_SIZE=25
SANAD_QURAN_MAX_RESULTS=5
SANAD_ENABLE_REMOTE_SEMANTIC=false
SANAD_ENABLE_SEMANTIC_RERANK=false
```

Never upload this `.env` file to GPT Work, Codex, GitHub, or a public repository unless the platform provides a dedicated secret manager and you enter values there privately.

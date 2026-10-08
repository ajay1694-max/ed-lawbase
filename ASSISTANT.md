# Ask LawBase

The research assistant searches only the public judgment database and supplies
short, source-linked guidance. Public research headnotes are identified separately
from judgment extracts. Private packs, personal notes and submitted PDFs are never
read for an AI prompt. Questions require confirmation that they contain no private
case facts. Identifier detection is an additional check, not complete redaction.

The default model is `gpt-6-luna`, with reasoning disabled and at most 1,200 output
tokens. `app/ai-policy.json` sets a $2 monthly allowance shared by all members,
20 AI requests per account per day, 24-hour answer caching and no automatic
upgrades, retries or alternate-provider calls. One AI request runs at a time;
network waits hold no search processing slot or corpus connection.

Reservations are recorded in ignored `data/research.sqlite` and survive restarts.
The allowance uses a conservative byte-based input estimate and the complete
output cap at standard prices of $0.10/$0.50 per million input/output tokens.
Failed calls retain their reservation. This limits this app's requests; it does
not control other applications using the same OpenAI balance, taxes or future
provider price changes. Recheck prices before changing the policy.

The existing key is read server-side from `OPENAI_API_KEY` or ignored
`data/ai-secrets.json`. On the approved VM the latter is owned by the service
account with mode 0600. Never commit or print its contents. No key is returned
to browsers. `store: false` is used on Responses requests; this does not itself
promise zero provider retention. No prompt/answer log is written by this app;
the budget ledger records only account, day, month and reserved cost.

Answers are rejected if a reference is outside the retrieved source set or a
quotation does not match an extract. This validates references and quotations,
not legal entailment. Officers must read the full original, distinguish arguments
from holdings, and check later history before using an answer in official work.
If a key is missing, a limit is reached or a call fails, local source judgments
remain available. There is no paid call when no relevant source is found.

Validation: `python -m unittest discover -s tests -p test_assistant.py` exercises
privacy opt-in, attached-private-database exclusion, fabricated references,
quotation checks, concurrent budget reservations, caching, failure behavior and
the provider request contract. Hosted authentication/origin tests remain in
`tests/test_research_http.py`. Live response quality needs corpus-specific checks.

Provider documentation:
- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/structured-outputs

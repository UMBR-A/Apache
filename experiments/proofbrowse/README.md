# ProofBrowse

A **working, deliberately narrow** AI browser researcher inspired by the large [Browser Use](https://github.com/browser-use/browser-use) project. Instead of competing on every browser task, ProofBrowse prioritizes **page-grounded answers, constrained actions, explicit human approval, and tamper-evident receipts**.

## What is different?

- **Observed quote required for completion:** to finish, the model must supply a quote found in the currently observed page. The answer, URL, and evidence are returned together.
- **Policy outside the LLM:** only allowlisted HTTP(S) destinations; private/loopback IP literals and local hostnames blocked. Navigation requests (including redirects) are checked before they proceed.
- **Default read-only:** filling fields and clicking buttons require an interactive YES, enabled with `--interactive`. Following links navigates to their href without running page click handlers, within the domain allowlist.
- **Action-by-action verification:** compare observed URL/page text before and after actions or validate `expected_text`; uncertain actions are marked `unverified`, never silently claimed successful.
- **Tamper-evident JSONL receipts:** a SHA-256 hash chain of events, with typed values hashed rather than recorded verbatim. `verify` checks if existing events were changed.
- **Local AI:** uses Ollama's JSON chat endpoint; no hosted AI key needed. You choose the model.

## Run

Python 3.10+ and a running [Ollama](https://ollama.com) installation are required.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
ollama pull llama3.2:3b
ollama serve                     # omit if Ollama is already running
proofbrowse run --url https://www.python.org \
  --allow-domain python.org \
  --task 'Find the exact text of the heading on the homepage'
proofbrowse verify proofbrowse-receipts.jsonl
```

Optionally add `--interactive --show-browser` to approve form fills or button clicks during exploration. The default `--max-steps` is 12. To use another installed model, specify `--model NAME`.

## Scope and known limitations

This is an **MVP, not a claim of general superiority** to Browser Use. It is designed for public-web research, not transactional workflows. The quote check proves that a matching excerpt was observed; it does **not** prove the excerpt is factually true, nor does the hash chain prove the recording was truthful at creation time. Domain allowlisting and navigation interception are not a hardened security sandbox: DNS rebinding, third-party resources, unsafe effects of GET requests, and model-origin prompt injection remain risks. Do not connect personal accounts or secrets, and run untrusted sites in an isolated browser/container. The model may need several tries or fail on complicated websites.

The project contains no copied Browser Use source. Its default LLM API is Ollama's public local JSON API and its browser backend is Playwright.

## Test

```bash
python -m unittest discover -s tests -v
```

## Roadmap

Next: browser integration smoke tests, evidence spans with stable DOM references, sandboxed network enforcement, model eval against benchmark websites, and side-by-side comparison with browser-use on fixed tasks.


## Repeatable Browser Use comparison (v0.2)

The `benchmark/` harness evaluates ProofBrowse and Browser Use against **identical
read-only public web tasks**. Both use the same Ollama checkpoint by default.
There are no precomputed performance claims: run both agents and review
`benchmark-results/report.json` for task correctness and wall-clock timings.

```bash
# Validate the fixture list without contacting a model or the web:
python -m benchmark.run --dry-run

# From the experiments/proofbrowse directory, with Ollama serving llama3.2:3b:
python -m pip install -e '.[browser]'
python -m pip install 'browser-use==1.0.5'  # comparison agent, optional
python -m playwright install chromium
ollama pull llama3.2:3b
python -m benchmark.run --agent both --model llama3.2:3b
```

These are three *smoke-test* fixtures, not a comprehensive leaderboard. A
fairer full study should include many independent websites, repeated runs,
model calls and token accounting, and controlled browser versions. Browser
Use's prompts and internal call budgets may differ even when checkpoint
weights match. Missing packages, timeouts, and failed tasks appear explicitly
in the report; they are not counted as wins. Neither agent should receive
credentials for these tests.

### Verification hardening in v0.2

- A final **answer must appear as a complete token/phrase within the cited
  observed quote**; previously, a genuine quote could accompany an unrelated
  fabricated answer. This makes answers extractive by design, not a proof of
  factual truth or safe handling of hostile pages.
- Navigation via links rejects `javascript:` and other non-HTTP(S) schemes
  before Playwright attempts to navigate.

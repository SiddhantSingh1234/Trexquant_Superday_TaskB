"""Phase 8 — the single LLM call path.

`call_llm(role, prompt, schema) -> dict` is the only way an agent talks to a
model.  Everything the budget reality (PRE_BUILD_TASKS.md T3) forces on us lives
here:

* **Startup model-availability probe** walking a per-tier fallback chain — no
  model ID is ever hard-coded (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`
  were reportedly deprecated 2026-06-17).
* **Token-bucket throttle (TPM)** — refills at ``tpm/60`` tokens/s; a call that
  would overdraw the bucket *sleeps* for the shortfall.
* **TPD counter** against a configured per-organisation cap; crossing it raises a
  **resumable** :class:`BudgetExhausted` *before* the request goes out, so no
  partial state is written.
* **Static-prefix caching** — the caller passes ``static_prefix=`` (rubric /
  operator list / corpus brief); its tokens are billed once per client and then
  counted as *cached* (cached tokens reportedly do not count toward limits).
* **JSON-schema validation + repair** — the model's text is coerced to the
  required shape or a clear error is raised after retries.
* **Offline mock mode** (`LLM_MODE=mock`) — canned, deterministic responses so
  the whole test suite runs with no network and no API key.

Nothing here writes a file, so a mid-call failure can never leave a partial
artifact — the resumability contract is satisfied structurally.
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import config

# Section 0.6 — determinism.
np.random.seed(config.RANDOM_SEED)
random.seed(config.RANDOM_SEED)

_PROMPT_DYNAMIC_MARKER = "=== DYNAMIC ==="


# ═════════════════════════════════════════════════════════════════════════════
#  Errors
# ═════════════════════════════════════════════════════════════════════════════
class BudgetExhausted(RuntimeError):
    """Raised when a call would push tokens-per-day past the configured cap.

    It is raised **before** the request is sent and before any agent mutates
    memory, so the run can be checkpointed and resumed the next day (Phase 10)
    with no partial write to undo.  Carries the numbers needed to resume.
    """

    def __init__(self, *, tier: str, used: int, cap: int, requested: int,
                 role: str | None = None) -> None:
        self.tier = tier
        self.used = int(used)
        self.cap = int(cap)
        self.requested = int(requested)
        self.role = role
        super().__init__(
            f"token budget exhausted for tier {tier!r}"
            + (f" (role {role!r})" if role else "")
            + f": used {used:,} + requested {requested:,} > cap {cap:,}. "
            f"Checkpoint and resume tomorrow."
        )


class NoModelAvailable(RuntimeError):
    """The startup probe walked the entire fallback chain and found nothing."""


class SchemaValidationError(ValueError):
    """The model's response could not be coerced to the required JSON shape."""


# ═════════════════════════════════════════════════════════════════════════════
#  Token estimation + JSON extraction
# ═════════════════════════════════════════════════════════════════════════════
def estimate_tokens(text: str) -> int:
    """Cheap token estimate: ~4 chars/token (the standard rule of thumb)."""
    if not text:
        return 0
    return max(1, math.ceil(len(str(text)) / 4))


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_json_object(text: str) -> str:
    """Pull the first balanced ``{...}`` out of a possibly-chatty response."""
    s = str(text).strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    start = s.find("{")
    if start == -1:
        raise SchemaValidationError("no JSON object found in model response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    raise SchemaValidationError("unbalanced JSON object in model response")


def parse_json(raw: str) -> dict:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        obj = json.loads(_extract_json_object(raw))
    if not isinstance(obj, dict):
        raise SchemaValidationError(f"expected a JSON object, got {type(obj)!r}")
    return obj


# ═════════════════════════════════════════════════════════════════════════════
#  Lightweight JSON-schema validation + coercion
# ═════════════════════════════════════════════════════════════════════════════
def validate_and_coerce(obj: dict, schema: dict | None) -> dict:
    """Validate ``obj`` against a tiny schema dialect and coerce where safe.

    Schema keys (all optional):
      * ``required``: list of keys that must be present and non-null
      * ``types``:    ``{key: type}`` — ``int``/``float``/``str``/``bool``/
                      ``list``/``dict`` (coercion attempted for scalars)
      * ``enum``:     ``{key: [allowed, ...]}``
      * ``defaults``: ``{key: value}`` applied when the key is absent
    """
    if schema is None:
        return obj
    out = dict(obj)

    for k, v in (schema.get("defaults") or {}).items():
        out.setdefault(k, v)

    for k in schema.get("required", []):
        if k not in out or out[k] is None:
            raise SchemaValidationError(f"missing required key: {k!r}")

    for k, typ in (schema.get("types") or {}).items():
        if k not in out or out[k] is None:
            continue
        val = out[k]
        if typ in (list, dict, bool):
            if not isinstance(val, typ):
                raise SchemaValidationError(
                    f"key {k!r} must be {typ.__name__}, got {type(val).__name__}"
                )
            continue
        try:
            if typ is int:
                out[k] = int(val)
            elif typ is float:
                out[k] = float(val)
            elif typ is str:
                out[k] = str(val)
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"key {k!r} could not be coerced to {typ.__name__}: {exc}"
            ) from exc

    for k, allowed in (schema.get("enum") or {}).items():
        if k in out and out[k] not in allowed:
            raise SchemaValidationError(
                f"key {k!r}={out[k]!r} not in {list(allowed)}"
            )
    return out


# ═════════════════════════════════════════════════════════════════════════════
#  Prompt loading  (static prefix / dynamic body split)
# ═════════════════════════════════════════════════════════════════════════════
_PROMPT_CACHE: dict[str, tuple[str, str]] = {}


def load_prompt(name: str) -> tuple[str, str]:
    """Return ``(static_prefix, dynamic_template)`` for ``prompts/<name>.txt``.

    The static prefix is everything before ``=== DYNAMIC ===`` — the rubric /
    operator list / conventions that never change between calls, so it caches.
    """
    if name in _PROMPT_CACHE:
        return _PROMPT_CACHE[name]
    p = Path(config.AGENT_PROMPTS_DIR) / f"{name}.txt"
    text = p.read_text(encoding="utf-8")
    if _PROMPT_DYNAMIC_MARKER in text:
        static, dyn = text.split(_PROMPT_DYNAMIC_MARKER, 1)
        pair = (static.strip() + "\n", dyn.strip())
    else:
        pair = ("", text.strip())
    _PROMPT_CACHE[name] = pair
    return pair


# ═════════════════════════════════════════════════════════════════════════════
#  Token-bucket throttle (TPM)
# ═════════════════════════════════════════════════════════════════════════════
class _TokenBucket:
    """Classic token bucket: capacity == ``tpm``, refill ``tpm/60`` per second.

    :meth:`consume` returns the seconds it slept (0 if the bucket had room).
    A request larger than the whole bucket drains it and sleeps for one full
    refill period rather than stalling forever.
    """

    def __init__(self, tpm: int, clock: Callable[[], float],
                 sleep: Callable[[float], None]) -> None:
        self.capacity = float(max(tpm, 1))
        self.rate = self.capacity / 60.0
        self.tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._t = clock()

    def _refill(self) -> None:
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self._t) * self.rate)
        self._t = now

    def consume(self, n: float) -> float:
        self._refill()
        need = min(float(n), self.capacity)
        if self.tokens >= need:
            self.tokens -= need
            return 0.0
        deficit = need - self.tokens
        wait = deficit / self.rate
        self._sleep(wait)
        self._refill()
        self.tokens = max(0.0, self.tokens - need)
        return wait


# ═════════════════════════════════════════════════════════════════════════════
#  TPD budget  (per organisation, resumable)
# ═════════════════════════════════════════════════════════════════════════════
def _today() -> str:
    return date.today().isoformat()


class TokenBudget:
    """Tokens-per-day counter for one model tier, shared across its roles.

    Rolls over automatically at midnight (local date).  :meth:`check` raises
    :class:`BudgetExhausted` if committing ``n`` more tokens would cross the cap
    — call it before doing anything irreversible.  Optionally mirrors state to a
    JSON file so a killed run resumes with the day's spend intact.
    """

    def __init__(self, tier: str, *, cap: int, used: int = 0,
                 day: str | None = None, path: str | Path | None = None) -> None:
        self.tier = tier
        self.cap = int(cap)
        self.used = int(used)
        self.day = day or _today()
        self.path = Path(path) if path else None

    # -- rollover / persistence --------------------------------------
    def _rollover(self) -> None:
        t = _today()
        if t != self.day:
            self.day = t
            self.used = 0

    def to_dict(self) -> dict:
        return {"tier": self.tier, "cap": self.cap, "used": self.used, "day": self.day}

    @classmethod
    def from_dict(cls, d: dict, *, path: str | Path | None = None) -> "TokenBudget":
        return cls(d["tier"], cap=int(d["cap"]), used=int(d.get("used", 0)),
                   day=d.get("day"), path=path)

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = {}
        if self.path.exists():
            try:
                blob = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                blob = {}
        blob[self.tier] = self.to_dict()
        self.path.write_text(json.dumps(blob, indent=2, sort_keys=True), encoding="utf-8")

    # -- the two operations -----------------------------------------
    def remaining(self) -> int:
        self._rollover()
        return max(0, self.cap - self.used)

    def check(self, n: int, *, role: str | None = None) -> None:
        self._rollover()
        if self.used + int(n) > self.cap:
            raise BudgetExhausted(tier=self.tier, used=self.used, cap=self.cap,
                                  requested=int(n), role=role)

    def commit(self, n: int) -> None:
        self._rollover()
        self.used += int(n)
        self._save()


# ═════════════════════════════════════════════════════════════════════════════
#  Startup model-availability probe
# ═════════════════════════════════════════════════════════════════════════════
def _mock_checker(_model: str) -> bool:
    return True


def _live_checker_factory(api_key: str) -> Callable[[str], bool]:
    def _check(model: str) -> bool:  # pragma: no cover - needs network + key
        if not api_key:
            return False
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            client.models.retrieve(model)
            return True
        except Exception:
            return False

    return _check


def _ollama_checker_factory(host: str) -> Callable[[str], bool]:
    def _check(model: str) -> bool:  # pragma: no cover - needs local Ollama
        try:
            import requests

            r = requests.get(f"{host}/api/tags", timeout=3)
            names = {m.get("name", "").split(":")[0] for m in r.json().get("models", [])}
            return model.split(":")[0] in names
        except Exception:
            return False

    return _check


def probe_model_chain(
    chain: list[str] | tuple[str, ...],
    *,
    mode: str = "mock",
    checker: Callable[[str], bool] | None = None,
    api_key: str = "",
    ollama_host: str = "",
) -> tuple[str, list[str]]:
    """Walk ``chain`` and return ``(first_available_model, tried)``.

    ``checker`` overrides availability detection (the test hook).  Otherwise the
    check depends on ``mode``: ``mock`` -> always available (offline),
    ``live`` -> Groq ``models.retrieve``, ``offline`` -> Ollama ``/api/tags``.
    Raises :class:`NoModelAvailable` if nothing in the chain answers.
    """
    if checker is None:
        if mode == "mock":
            checker = _mock_checker
        elif mode == "offline":
            checker = _ollama_checker_factory(ollama_host or config.OLLAMA_HOST)
        else:
            checker = _live_checker_factory(api_key or config.GROQ_API_KEY)
    tried: list[str] = []
    for model in chain:
        tried.append(model)
        try:
            if checker(model):
                return model, tried
        except Exception:
            continue
    raise NoModelAvailable(
        f"no model available in chain {list(chain)} (mode={mode!r}); "
        f"tried {tried}"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  The client
# ═════════════════════════════════════════════════════════════════════════════
class LLMClient:
    """One model client per agent role.

    Stateless between calls except for the accounting counters and the set of
    static-prefix hashes it has already paid for (the cache).  Construct one per
    role; the Economics Reviewer must get its *own* instance (see
    ``build_agents``).
    """

    def __init__(
        self,
        role: str,
        *,
        mode: str | None = None,
        model: str | None = None,
        tier: str | None = None,
        tpm: int | None = None,
        rpm: int | None = None,
        tpd_cap: int | None = None,
        budget: TokenBudget | None = None,
        probe: bool = True,
        model_checker: Callable[[str], bool] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        fixtures: dict | None = None,
        max_retries: int = 2,
    ) -> None:
        self.role = role
        self.mode = (mode or config.LLM_MODE).strip().lower()
        self.tier = tier or config.LLM_ROLE_TIER.get(role, "small")
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self.max_retries = int(max_retries)

        chain_key = "offline" if self.mode == "offline" else self.tier
        self.chain: list[str] = list(config.LLM_MODEL_CHAINS[chain_key])

        self.tpm = int(tpm if tpm is not None else config.LLM_TPM[self.tier])
        self.rpm = int(rpm if rpm is not None else config.LLM_RPM[self.tier])
        cap = int(tpd_cap if tpd_cap is not None else config.LLM_TPD_CAP[self.tier])
        self.budget = budget or TokenBudget(self.tier, cap=cap)

        self._bucket = _TokenBucket(self.tpm, self._clock, self._sleep)
        self._min_interval = 60.0 / max(self.rpm, 1)
        self._last_call_t: float | None = None

        # accounting
        self.billed_tokens = 0
        self.cached_tokens = 0
        self.n_calls = 0
        self.total_wait_s = 0.0
        self._seen_prefixes: set[str] = set()

        # mock fixtures
        from . import mock_fixtures

        self.fixtures = fixtures if fixtures is not None else mock_fixtures.FIXTURES

        self.model = model
        if self.model is None and probe:
            self.model, self._probe_tried = probe_model_chain(
                self.chain, mode=self.mode, checker=model_checker,
                api_key=config.GROQ_API_KEY, ollama_host=config.OLLAMA_HOST,
            )
        else:
            self._probe_tried = [self.model] if self.model else []

        # Rate limits are a property of the MODEL, not the tier, and the probe may
        # have walked past the tier's head to a fallback.  Now that the model is
        # known, re-derive from its measured limits.  An explicitly-passed value
        # always wins — callers (and tests) that pin tpm/rpm/tpd_cap keep theirs.
        lim = config.LLM_MODEL_LIMITS.get(self.model or "")
        if lim:
            if tpm is None and "tpm" in lim and int(lim["tpm"]) != self.tpm:
                self.tpm = int(lim["tpm"])
                self._bucket = _TokenBucket(self.tpm, self._clock, self._sleep)
            if tpd_cap is None and budget is None and "tpd_cap" in lim:
                self.budget = TokenBudget(self.tier, cap=int(lim["tpd_cap"]))
        # measured requests-per-day ceiling for this model (see config); recorded
        # so a caller can check it — `TokenBudget` covers tokens/day, not requests.
        self.rpd = int((lim or {}).get("rpd", config.LLM_RPD.get(self.tier, 0)))

    # -- accounting snapshot --------------------------------------
    @property
    def stats(self) -> dict:
        return {
            "role": self.role, "model": self.model, "n_calls": self.n_calls,
            "billed_tokens": self.billed_tokens, "cached_tokens": self.cached_tokens,
            "total_wait_s": round(self.total_wait_s, 3),
            "budget_used": self.budget.used, "budget_cap": self.budget.cap,
        }

    # -- the call path -------------------------------------------
    def call(self, prompt: str, schema: dict | None = None, *,
             static_prefix: str = "") -> dict:
        """Send ``prompt``, return a schema-valid dict (or raise after retries).

        ``static_prefix`` names the cacheable head of ``prompt`` (must be a
        prefix of it); its tokens are billed once per client, then free.
        """
        self.n_calls += 1

        if static_prefix and prompt.startswith(static_prefix):
            dyn_text = prompt[len(static_prefix):]
        else:
            dyn_text = prompt
            static_prefix = ""

        static_tok = estimate_tokens(static_prefix)
        dyn_tok = estimate_tokens(dyn_text)
        prefix_hash = _sha(static_prefix) if static_prefix else None

        prefix_billed = 0
        if prefix_hash is not None:
            if prefix_hash in self._seen_prefixes:
                self.cached_tokens += static_tok
            else:
                prefix_billed = static_tok  # committed only if the call proceeds

        completion_est = _completion_estimate(self.role, schema)
        est_total = prefix_billed + dyn_tok + completion_est

        # Budget FIRST — raises before the request goes out, no state mutated.
        self.budget.check(est_total, role=self.role)

        # Throttle: token bucket (TPM) then request spacing (RPM).
        self.total_wait_s += self._bucket.consume(est_total)
        self._space_requests()

        raw, completion_tok, model_used = self._dispatch(prompt, schema)
        self.model = model_used

        billed = prefix_billed + dyn_tok + int(completion_tok)
        if prefix_hash is not None and prefix_billed:
            self._seen_prefixes.add(prefix_hash)
        self.billed_tokens += billed
        self.budget.commit(billed)

        # Parse + validate, with repair retries.
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                obj = parse_json(raw)
                return validate_and_coerce(obj, schema)
            except (SchemaValidationError, json.JSONDecodeError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                raw, extra_tok, _ = self._dispatch(
                    prompt + _repair_hint(schema, exc), schema, repair=True
                )
                self.billed_tokens += int(extra_tok)
                self.budget.commit(int(extra_tok))
        raise SchemaValidationError(
            f"[{self.role}] response failed schema validation after "
            f"{self.max_retries + 1} attempts: {last_exc}"
        )

    __call__ = call

    # -- request spacing (RPM) ----------------------------------
    def _space_requests(self) -> None:
        now = self._clock()
        if self._last_call_t is not None:
            gap = now - self._last_call_t
            if gap < self._min_interval:
                wait = self._min_interval - gap
                self._sleep(wait)
                self.total_wait_s += wait
                now = self._clock()
        self._last_call_t = now

    # -- dispatch by mode --------------------------------------
    def _dispatch(self, prompt: str, schema: dict | None,
                  *, repair: bool = False) -> tuple[str, int, str]:
        if self.mode == "mock":
            return self._mock(prompt, schema, repair=repair)
        if self.mode == "offline":
            return self._ollama(prompt)  # pragma: no cover
        return self._groq(prompt)  # pragma: no cover

    def _mock(self, prompt: str, schema: dict | None,
              *, repair: bool = False) -> tuple[str, int, str]:
        from . import mock_fixtures

        fn = self.fixtures.get(self.role)
        if fn is None:
            raise NoModelAvailable(f"no mock fixture for role {self.role!r}")
        obj = fn(prompt, schema)
        raw = json.dumps(obj)
        comp = mock_fixtures.COMPLETION_TOKENS.get(self.role, 200)
        return raw, comp, (self.model or "mock:" + (self.chain[0] if self.chain else "none"))

    def _groq(self, prompt: str) -> tuple[str, int, str]:  # pragma: no cover
        from groq import Groq

        client = Groq(api_key=config.GROQ_API_KEY)
        last_exc = None
        for model in self.chain:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                usage = resp.usage
                return (resp.choices[0].message.content,
                        int(getattr(usage, "completion_tokens", 0)), model)
            except Exception as exc:
                last_exc = exc
                continue
        raise NoModelAvailable(f"every model in {self.chain} failed: {last_exc}")

    def _ollama(self, prompt: str) -> tuple[str, int, str]:  # pragma: no cover
        import requests

        for model in self.chain:
            try:
                r = requests.post(
                    f"{config.OLLAMA_HOST}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False,
                          "format": "json"},
                    timeout=120,
                )
                data = r.json()
                return (data.get("response", ""),
                        int(data.get("eval_count", 0)) or estimate_tokens(
                            data.get("response", "")), model)
            except Exception:
                continue
        raise NoModelAvailable(f"no Ollama model reachable in {self.chain}")


# per-role completion-token estimate (mock: exact; live: pre-call guess).
_COMPLETION_GUESS = {
    "hypothesis": 620, "redteam": 260, "coder": 200, "judge": 150,
    "economics": 340, "planner": 180, "librarian": 460, "reflection": 220,
}


def _completion_estimate(role: str, schema: dict | None) -> int:
    from . import mock_fixtures

    if role in mock_fixtures.COMPLETION_TOKENS:
        return mock_fixtures.COMPLETION_TOKENS[role]
    return _COMPLETION_GUESS.get(role, 200)


def _repair_hint(schema: dict | None, exc: Exception) -> str:
    req = (schema or {}).get("required", [])
    return (
        "\n\nYour previous reply was not valid. Return ONLY a JSON object"
        f" with keys {req}. Error: {exc}"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Module-level convenience: one shared client per role
# ═════════════════════════════════════════════════════════════════════════════
_CLIENTS: dict[str, LLMClient] = {}


def get_client(role: str, **kw) -> LLMClient:
    if role not in _CLIENTS:
        _CLIENTS[role] = LLMClient(role, **kw)
    return _CLIENTS[role]


def reset_clients() -> None:
    """Drop the cached per-role clients (tests / a fresh run)."""
    _CLIENTS.clear()


def call_llm(role: str, prompt: str, schema: dict | None = None, *,
             static_prefix: str = "", client: LLMClient | None = None) -> dict:
    """The one documented entry point (IMPLEMENTATION_PLAN.md Phase 8).

    Uses ``client`` if given, else a lazily-created shared client for ``role``.
    """
    c = client or get_client(role)
    return c.call(prompt, schema, static_prefix=static_prefix)

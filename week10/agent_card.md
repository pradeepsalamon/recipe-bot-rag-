# A2A Agent Card — Bonus Challenge

## AgentCard (JSON)

```json
{
  "name": "RecipeSubstitutionOrchestrator",
  "description": "Evaluates recipe substitutions for culinary viability, allergen safety, and recipe integrity using a team of specialist agents.",
  "version": "1.0.0",
  "url": "http://localhost:8000/a2a",
  "skills": [
    {
      "id": "evaluate_substitution",
      "name": "Evaluate Recipe Substitution",
      "description": "Given a recipe and a requested substitution, evaluates whether the substitution is culinarily viable, allergen-safe, and maintains recipe integrity.",
      "inputModes": [
        "text/plain",
        "application/json"
      ],
      "outputModes": [
        "application/json"
      ]
    },
    {
      "id": "check_allergens",
      "name": "Check Allergen Warnings",
      "description": "Validates allergen warnings against ingredient lists.",
      "inputModes": [
        "application/json"
      ],
      "outputModes": [
        "application/json"
      ]
    }
  ],
  "authentication": {
    "schemes": [
      "bearer"
    ],
    "credentials": null
  },
  "provider": {
    "organization": "Recipe Bot RAG",
    "url": "https://example.com"
  }
}
```

## Failed Case and A2A Task Lifecycle

The failed case (`case_22`) maps to the A2A task lifecycle as follows:

- **Initial state:** `submitted` — the orchestrator receives the evaluation request.
- **Working state:** `working` — the orchestrator delegates to the substitution worker and allergen worker.
- **On allergen worker 500:** The task should have transitioned to `input-required` rather than `failed`.
  - The correct A2A behaviour is to pause and ask the user: "The allergen check service is unavailable. Do you want to proceed with only the substitution viability check, or provide your allergy list manually?"
  - Instead, the orchestrator retried automatically, which is acceptable but loses the opportunity to get the user's actual allergy list (which would make the check more accurate).
- **Resolution:** The task should end as `failed` if no allergen data can be obtained, or `completed` if the retry succeeds or the user provides their allergy list.

## What A2A Buys Over Plain REST

1. **Structured task lifecycle** — A2A's state machine (submitted → working → input-required → completed/failed) lets the client observe, pause, and resume the task, whereas a plain REST call either succeeds or returns an error with no intermediate states.
2. **Capability discovery** — The AgentCard lets clients discover what the agent can do (skills, input/output modes) before calling it, whereas a REST endpoint requires out-of-band documentation and version-specific knowledge.
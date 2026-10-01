# Failure Case — Injected Worker 500 Error

## Setup

**Injected on:** `case_22`
**Worker affected:** Allergen Worker
**Failure type:** HTTP 500 Internal Server Error (simulated crash)

## What Happened

**Error message:** `HTTP 500 Internal Server Error: Allergen worker crashed on case_22`

**Orchestrator behaviour: RETRIED**

The orchestrator caught the 500 error from the allergen worker, waited 500ms, and retried the call. The retry succeeded, and the orchestrator proceeded to synthesise a verdict using both worker outputs normally.

This is the **correct behaviour** — the orchestrator did not lie by synthesising an allergen claim the worker never made, nor did it silently drop the allergen check.

**Final verdict for case_22:** Fail

## Evidence from Hand-off Log

Relevant log entries:
```
  orchestrator -> substitution_worker           | tok=  482
  orchestrator -> allergen_worker (FAILED — 500) | tok=    0 | ERROR: HTTP 500 Internal Server Error
  orchestrator -> allergen_worker               | tok=  474
  workers -> orchestrator_synthesis             | tok=  480
```

## One-line Summary

The orchestrator **retried** after the allergen worker's 500, the retry succeeded, and the final verdict was synthesised from real worker data — no allergen claims were fabricated.
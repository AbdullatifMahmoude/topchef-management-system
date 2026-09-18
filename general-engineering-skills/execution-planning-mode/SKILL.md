# Execution Planning Mode

Applies to any project. Before implementing anything beyond a trivial, one-line task: build an
explicit plan first, show it, and **explain the reasoning behind its shape** — not just the steps.
The explanation is the actual teaching moment; a plan with no "why" is just a to-do list.

## Skip this for trivial tasks
A one-line fix, a typo, a single obvious change — just do it. Planning ceremony around trivial work
teaches nothing and wastes time.

## How to build the plan
1. **Find the riskiest or most uncertain part first** — the part most likely to need a design
   decision, most likely to break something else, or that everything downstream depends on.
   Sequence it early, not last. Say explicitly why: "this comes first because if the approach here
   is wrong, steps 3-5 would need to be redone."
2. **Order by dependency, not convenience.** If B needs a decision made in A, A comes first — even
   if A is harder or B feels like a quicker win.
3. **Tag every step** with one of:
   - `[decision]` — a real judgment call, worth a beat of discussion (per Engineering Mentorship
     Mode) before executing it.
   - `[mechanical]` — no real judgment needed, just build it.
   - `[checkpoint]` — verify/test before continuing, especially right after a `[risk]` or
     `[decision]` step. Don't put every checkpoint at the end — catch problems where they're
     introduced.
4. **Keep it short.** Numbered list, one line per step, tag in front. Not paragraphs.

## Format
```
1. [decision] Define the idempotency-key storage — Redis vs. Postgres table. Blocks step 3.
2. [mechanical] Scaffold the endpoint and request/response models.
3. [risk] Implement the concurrent-write guard. Riskiest part — do it before anything depends on it.
4. [checkpoint] Write the two-concurrent-requests test before moving on.
5. [mechanical] Wire up the remaining CRUD endpoints.
```

## After presenting the plan
State in 1-3 sentences *why* it's ordered this way — which step is the riskiest and why it's not
last, what depends on what. This is deliberate: it's the part that teaches the person how to plan
their own work, not just what to build.

Then ask for one confirmation or adjustment before executing — don't just start coding
immediately after presenting the plan.

## While executing
When you reach a `[decision]` step, actually pause and discuss it (per Engineering Mentorship
Mode) rather than silently resolving it because it was "in the plan already." A plan sets the
order of decisions, it doesn't pre-answer them.

## After finishing
Briefly note whether reality matched the plan — did the riskiest step turn out to actually be the
hard part, or did something unplanned surface? This calibrates the person's own risk-sensing for
next time, which is the actual point of planning explicitly instead of just diving in.

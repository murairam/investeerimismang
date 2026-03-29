argument-hint: "<request>"
allowed-tools:
  - Bash
If no hook rules are present, start with:
`Applying rules: none returned by hook`

You must make the review loop visible in the conversation.

User request:
$ARGUMENTS

Follow this workflow exactly:
1. Start with `Applying rules: ...`
2. Write `Drafting initial plan.`
3. Produce `Draft 1` as a numbered plan that stays strictly within scope and uses the current repository context.
4. Review that exact draft by using Bash with this shape:
5. After each review tool call:
   - If it passes, write `Review N passed.`
   - If it fails, write `Review N found X violation(s): ...`
6. If a review fails and N < 3, write `Draft N+1` and revise only the listed violations. Do not widen scope.
7. Stop after a pass or after 3 total reviews.
8. End with `Final plan` and only the final numbered plan.
9. Never print raw review JSON directly to the user. Summarize it in one short sentence.

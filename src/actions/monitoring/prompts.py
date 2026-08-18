"""Default prompts for monitor scoring and reply drafting.

These are the fallbacks. The operator overrides any of them from the bot
(``/prompt <name>``), and the override lives in Redis - see
``monitor_settings.prompt``. Keeping the defaults in code means a reset always
has somewhere to go back to.

Why two scoring prompts rather than one prompt and two numbers: contour A is the
operator's own patch, where the cost of missing a job is high and the cost of a
false alarm is low; contour B is everything else, where it is the other way
round. Same model, opposite instruction - so they cannot share a body.
"""

from __future__ import annotations

# Prompt names, used as the Redis suffix and as the bot command argument.
SCORE_A = "a"
SCORE_B = "b"
DRAFT = "draft"

PROMPT_NAMES = (SCORE_A, SCORE_B, DRAFT)


# The part both scoring prompts share: what the job is and how to read the
# profile. Anything contour-specific belongs in the two bodies below.
_SCORING_COMMON = """You rate how well one freelance job posting fits a specific contractor.

You will be given the contractor profile in up to three blocks:
- MY LISTINGS: services he already sells on the marketplaces. A match here is the
  strongest possible signal - the client can open his profile and immediately see
  a ready-made offer for exactly what he asked for.
- MY OWN PRODUCTS: working software he owns but has not listed anywhere. A match
  here is also strong, but the pitch is different - there is no listing to point
  at, only a product that already runs.
- WHAT I HAVE WORKED WITH: general experience. Use it for jobs that fit no
  listing and no product but that he plainly can do.

Rate honestly. If the job needs something he has never touched and could not pick
up quickly, say so and score low. Do not invent experience that is not in the
profile.

Score only relevance - whether he can do this job well. Ignore the budget, the
number of competing offers and how fresh the posting is: those are filtered
separately, and mixing them into the score makes it impossible to tell why an
item was rejected.

Fill the fields as follows:
- score: 0-100, how well this fits.
- match_type: where the match came from - "listing" (matches a service he already
  sells), "product" (matches one of his own products), "skill" (no listing or
  product, but clear relevant experience), "adjacent" (related field, would have
  to learn part of it), "none" (not his field at all).
- matched_offer: the name of the listing or product that matched, empty if none.
- have: what the job asks for that he has demonstrably done before.
- gap: what the job asks for that is missing from the profile.
- verdict: "take" / "look" / "skip".
- reason: one short sentence, in Russian, explaining the score.

Answer in Russian for the text fields (reason, have, gap)."""


DEFAULT_PROMPTS: dict[str, str] = {
    SCORE_A: _SCORING_COMMON
    + """

This posting is in a category the contractor marked as his own patch. Read it
looking for a reason to take it: what part of the job he has already done, which
of his listings comes closest. Missing a good job here costs more than an extra
notification, so when the fit is arguable, lean towards the higher score.""",
    SCORE_B: _SCORING_COMMON
    + """

This posting is outside the categories the contractor marked as his. Most jobs
here are noise. Score high only when the match is unmistakable - it lines up with
one of his listings or with one of his own products. General "he is a programmer,
this is programming" reasoning is not enough. When in doubt, score low: an extra
notification here costs more than a missed job.""",
    DRAFT: """You write the first message a freelancer sends to a client about a job posting.

Write in Russian, as a human writes to another human. Rules:

- Open with what you will do for him, not with who you are.
- Name a concrete approach in one or two sentences: what he gets, in what form.
- State a deadline and a price, or say plainly what you need in order to name them.
- The budget in the posting is what the *client* named. It is his ceiling, not
  your quote. Never repeat it back as your own price. Either name a price that
  follows from the work described, or say what you need in order to name one.
  If the stated budget is far below what the job actually takes, say so in one
  line instead of silently agreeing to it.
- At most one clarifying question, and only when the job genuinely cannot be
  estimated without it.
- No technical vocabulary. Not a single library, framework or model name. The
  client is not a programmer and words like these read as showing off.
- No greetings longer than one line, no "I am a professional with N years of
  experience", no lists of technologies, no flattery about his project.
- 4 to 8 lines. Shorter is better.

The point is a message the contractor can send after changing two words.""",
}


def default_prompt(name: str) -> str:
    return DEFAULT_PROMPTS.get(name, "")

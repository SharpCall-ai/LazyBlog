You are writing one blog post for SharpCall.ai — an AI receptionist for Canadian
small businesses: restaurants, salons and spas, medical and dental, real estate,
auto services, plumbing and HVAC, and professional services.

The reader owns or runs one of those businesses. They are not technical, they are
busy, and they are losing calls they never hear about. Write for them.

Return a single JSON object. No prose, no code fences, no commentary.

```json
{
  "title": "Post title, under 60 characters",
  "slug": "kebab-case-from-the-primary-keyword",
  "description": "One sentence under 155 characters, for the meta description.",
  "category": "Guide",
  "keywords": ["primary keyword", "secondary keyword"],
  "body": "The post as GitHub-flavoured markdown.",
  "faqs": [{ "q": "A real question", "a": "A direct, complete answer." }]
}
```

Rules for `body`:

- 1,200-1,800 words of markdown. Open with the answer, not a warm-up paragraph.
- `##` and `###` for structure. No `#` heading — the page renders the title itself.
- Tables and lists where they genuinely help. A comparison post should have a table.
- Practical and specific to the topic's industry. Cite concrete scenarios — the
  dinner rush, the 2am burst pipe, the front desk with two lines ringing — not
  "in today's fast-paced world".
- Link naturally to the pages given with the topic, once each, where they fit.
- **No invented statistics, and no invented sources.** This is the rule that matters
  most, and the one models break most often. Specifically forbidden:
  - Attributing a number to a named body (Statistics Canada, a university, "a 2025
    study", "industry research") unless that exact figure appears on a linked page.
    Every widely-quoted stat in this industry - percentages of calls unanswered,
    dollars lost per missed call, share of callers who never call back - traces back
    to vendor marketing with no underlying study. Do not repeat any of them.
  - Stating what SharpCall does, integrates with, costs or supports unless it is on
    a linked page. If you do not know, describe what to look for in a provider
    instead of asserting a SharpCall capability.
  - Naming a competitor's price, feature or limitation as fact.
  You may reason with arithmetic the reader supplies themselves, clearly framed as
  an illustration: "if a table is worth $80 and you miss two a night, that is $160".
  Frame it as their number to check, never as measured fact. A made-up stat is worse
  than no stat: it is the one thing that destroys trust, and it is legally risky.
- No em dashes anywhere. Use hyphens or restructure the sentence.
- Canadian spelling and Canadian context. This is not a US business.

Rules for `faqs`: 3-5 entries, each answer complete on its own. They render on the
page and feed FAQPage structured data, so a half-answer costs a rich result.

## The columns that come with a topic

- `cluster`: which group of posts this belongs to. Stay in your lane - a
  `vertical-trades` post is for a contractor, not a general small-business reader.
- `intent`: what the searcher wants.
  - `informational` - they are learning. Answer the question first, sell nothing.
  - `commercial` - they are comparing options. A comparison table earns its place.
  - `transactional` - they are close to switching. Be concrete about what changes.
- `review`: how carefully a human will check this before it goes out.
  - `standard` - normal care.
  - `legal` - the post makes regulatory claims (PIPEDA, PHIPA, Bill 96, Law 25,
    CRTC, call-recording consent). State the general rule, say plainly that it is
    not legal advice, and tell the reader to confirm with counsel for their
    situation. Do not state penalty amounts, thresholds or deadlines as fact.
  - `competitor` - the post names another company. Describe categories of product
    and what to check for. Never assert a named competitor's pricing or features.

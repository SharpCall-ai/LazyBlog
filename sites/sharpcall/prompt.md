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
- **No invented statistics.** If you cite a number it must come from the linked
  pages, or be clearly framed as an illustration ("say a table is worth $80...").
  A made-up stat is worse than no stat: it is the one thing that destroys trust.
- No em dashes anywhere. Use hyphens or restructure the sentence.
- Canadian spelling and Canadian context. This is not a US business.

Rules for `faqs`: 3-5 entries, each answer complete on its own. They render on the
page and feed FAQPage structured data, so a half-answer costs a rich result.

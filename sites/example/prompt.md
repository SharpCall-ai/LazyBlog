You are writing one blog post for Example Co, which makes widgets for small
businesses. Replace this paragraph with who you are, who reads you, and what you
sell. The more specific it is, the less generic the post reads.

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
- `##` and `###` for structure. Tables, lists and `**bold**` where they earn it.
- No `#` heading — the page renders the title itself.
- Be concrete. Cite real scenarios (the dinner rush, the 2am burst pipe), never
  "in today's fast-paced world".
- No invented statistics. A number either comes from a page in `sources` or is
  clearly framed as an illustration.
- No em dashes. Use hyphens or restructure the sentence.

Rules for `faqs`: 3-5 entries, each answer complete on its own. They render on the
page and feed FAQPage structured data, so a half-answer costs a rich result.

## Your own columns

Any column you add to `topics.csv` arrives here as a `key: value` line with the
topic. Explain what yours mean, like this one:

- `tone`: `blunt` means short sentences and no throat-clearing. `friendly` means a
  warmer, second-person voice. Ignore any tone you do not recognise.

Delete this section if you only use the standard columns.

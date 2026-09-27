# Explanation

These pages explain why the template works the way it does: the decisions,
the alternatives that were rejected, and the trade-offs. Read them when you
want to adapt the template, or when a rule seems arbitrary.

| Page | Question it answers |
|---|---|
| [Design overview](design-overview.md) | Why an LLM wiki, why OKF, why the vault is the bundle, why generated indexes and a log, why a Copier template. |
| [Links and relations](links-and-relations.md) | Why bundle-absolute markdown links, and why every typed relation also needs a link in the prose. |
| [Provenance and trust](provenance-and-trust.md) | How a page records who wrote it, what it rests on, whether a human checked it, and when it expires. |
| [External resources](external-resources.md) | Why PDFs and web archives stay outside the repository, and how deny rules keep private material out. |
| [Maintenance analytics](maintenance-analytics.md) | How the link graph, duplicate candidates and unlinked mentions are computed, and why they are candidates rather than decisions. |
| [Agents and hooks](agents-and-hooks.md) | How agents learn the conventions, and how hooks, pre-commit and CI enforce them. |

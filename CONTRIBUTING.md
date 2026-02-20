# Contributing to DojoTesuto

Thanks for your interest in making the dojo stronger. 🥋

## Ways to Contribute

- **New quests** — Add adversarial challenges to `challenges/`. See `dojotesuto/schema.md` for the format.
- **Bug fixes** — Open an issue first for anything significant.
- **Documentation** — Improvements to README, schema docs, or inline comments are always welcome.

## Quest Guidelines

A good quest:
- Tests a real failure mode agents encounter in production
- Has a clear primary challenge AND at least one meaningful variant
- Variants must test the *same concept* with different surface details — not just rephrasing

## Running Tests

```bash
pytest tests/
python -m dojotesuto.validator
```

## Pull Request Process

1. Fork the repo and create a branch
2. Make your changes
3. Run tests and validator — both must pass
4. Submit a PR with a clear description of what you added and why

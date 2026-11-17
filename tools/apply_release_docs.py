from pathlib import Path
p=Path("README.md")
s=p.read_text()
needle="## Start here: four steps"
assert needle in s
s=s.replace(needle, """## Reproducible synthetic demonstration

Run `python tools/prepare_release_demo.py` before `python -m gridregime.demo`
to create a local **synthetic** EIA-930-shaped input. This is not historical
PJM evidence. See [offline demo instructions](docs/release-demo.md).

"""+needle,1)
p.write_text(s)
p=Path("docs/cross-domain-architecture.md")
s=p.read_text()
needle="## Implemented on integration branch"
assert needle in s
s=s.replace(needle,"## Implemented in the consolidated repository",1)
needle="## Not yet implemented"
assert needle in s
s=s[:s.index(needle)]+"""## Remaining limitations

The repository contains OAF acquisition and operational adapters, deterministic
analysis, artifact checksums, and optional Redis integration. It does not
provide authenticated model promotion, a production scheduler, independently
validated emergency prediction, or demonstrated live publication-time guarantees.
The in-process acquisition walkthrough is not a durable recovery test.
"""
p.write_text(s)
print("Updated documentation")

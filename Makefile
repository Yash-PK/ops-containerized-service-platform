PYTHON ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
SHELL := /bin/bash
.PHONY: help bootstrap doctor lint test validate demo integration integration-dev security clean-clone clean gate publish teardown teardown-plan
help:
	@printf '%s\n' 'bootstrap: install hash-locked dependencies/tools locally' 'doctor: inspect tools and optional VM prerequisites' 'lint: Ruff, ShellCheck, shfmt, actionlint, documents/configuration' 'test: unit and safety regression tests; no containers' 'validate: required local lint/tests' 'demo: deterministic text analysis and safe lab dry-run' 'integration LAB=ops-container-platform-reference: real owned VM/Compose lifecycle, clean commit required' 'integration-dev LAB=ops-container-platform-reference: same real workflow, ignored development evidence' 'security: scan working files, staged blobs and full outgoing history' 'clean-clone: execute standalone quickstart from temporary clone' 'clean: print teardown plan only' 'teardown LAB=id CONFIRM=id: remove only inventoried lab VM if cleanup failed' 'gate: require matching controller/clone/Compose evidence and current checks' 'publish: credential-free gated publishing script'
bootstrap:
	$(PYTHON) scripts/bootstrap.py
	.venv/bin/python scripts/bootstrap_provider.py
doctor:
	$(PYTHON) scripts/doctor.py
lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.tools/bin/shellcheck scripts/demo.sh containers/*.sh
	.tools/bin/shfmt -d -i 2 scripts/demo.sh containers/*.sh
	PATH="$(CURDIR)/.tools/bin:$$PATH" .tools/bin/actionlint
	$(PYTHON) scripts/quality.py
	$(PYTHON) scripts/config_check.py
test:
	$(PYTHON) -m unittest discover -s tests -v
validate: lint test
demo:
	bash scripts/demo.sh
integration:
	$(PYTHON) scripts/lab.py integration --lab-id "$(LAB)" --confirm "$(LAB)" --execute
integration-dev:
	$(PYTHON) scripts/lab.py integration --lab-id "$(LAB)" --confirm "$(LAB)" --execute --development
security:
	$(PYTHON) scripts/security.py
clean-clone:
	$(PYTHON) scripts/clean_clone.py
clean:
	$(PYTHON) scripts/lab.py teardown --lab-id ops-container-platform-reference
teardown-plan:
	$(PYTHON) scripts/lab.py teardown --lab-id "$(LAB)"
teardown:
	$(PYTHON) scripts/lab.py teardown --lab-id "$(LAB)" --confirm "$(CONFIRM)" --execute
gate: doctor validate demo security
	$(PYTHON) scripts/evidence.py
publish:
	$(PYTHON) scripts/publish.py

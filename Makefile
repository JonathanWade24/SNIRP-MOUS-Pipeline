PYTHON ?= python3
PYTEST ?= pytest
TEST_DIR ?= tests
PYTEST_MARK_FAST ?= not integration and not slow
PYTEST_N ?= auto

.PHONY: test test-quick test-full test-parallel test-quick-parallel

test: test-quick

test-quick:
	$(PYTEST) -m "$(PYTEST_MARK_FAST)" $(TEST_DIR)

test-full:
	$(PYTEST) $(TEST_DIR)

test-parallel:
	@if $(PYTHON) -c "import xdist" >/dev/null 2>&1; then \
		$(PYTEST) -n $(PYTEST_N) $(TEST_DIR); \
	else \
		echo "pytest-xdist not installed; running serial pytest."; \
		$(PYTEST) $(TEST_DIR); \
	fi

test-quick-parallel:
	@if $(PYTHON) -c "import xdist" >/dev/null 2>&1; then \
		$(PYTEST) -n $(PYTEST_N) -m "$(PYTEST_MARK_FAST)" $(TEST_DIR); \
	else \
		echo "pytest-xdist not installed; running serial quick pytest."; \
		$(PYTEST) -m "$(PYTEST_MARK_FAST)" $(TEST_DIR); \
	fi

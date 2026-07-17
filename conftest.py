"""Root-level conftest: fixtures that apply to every test in the suite."""
import pytest
import compress_roms as _rs


@pytest.fixture(autouse=True)
def _clear_disc_dir_cache():
    """Clear compress_roms._disc_dir_cache before and after each test.

    The cache is a module-level dict keyed by directory path string.
    Without clearing it, a test that scans a directory without a .cue file
    could pollute later tests that ADD a .cue to the same path.
    tmp_path gives each test a unique directory, so in practice collisions are
    rare, but clearing is cheap and makes the suite order-independent.
    """
    _rs._disc_dir_cache.clear()
    yield
    _rs._disc_dir_cache.clear()

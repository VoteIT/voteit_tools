from voteit.core.testing import load_doctests

import voteit_tools


def load_tests(loader, tests, pattern):
    load_doctests(tests, voteit_tools)
    return tests

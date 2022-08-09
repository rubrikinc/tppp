from __future__ import absolute_import

from test_drain3_consumer import TestDrain3Consumer

if __name__ == "__main__":
    # execute only if run as a script
    test_obj = TestDrain3Consumer()
    test_obj.run_unittests()

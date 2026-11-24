"""Run this project's full unittest suite plus the window business checks."""
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    if not successful:
        return 1
    try:
        from window_fixture import verify_v1, verify_window, verify_window_business
        verify_v1()
        verify_window()
        signed = verify_window_business()
    except BaseException as error:  # noqa: BLE001 - report any check failure
        print(f'WINDOW CHECK FAILED {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    print('WINDOW SUMMARY result=PASS '
          f'report_id={signed.report_id} '
          f'window={list(signed.draft.window)} '
          f'first_differences={[(beat, str(mass)) for beat, mass in signed.draft.first_differences]} '
          f'always_same={signed.draft.always_same}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

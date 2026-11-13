"""Keep the latest exception across reboots without logging every UI frame."""
import sys


def record(error, context='fatal'):
    print('FAULT', context)
    sys.print_exception(error)
    try:
        with open('last_error.log', 'w') as output:
            output.write('Context: ' + context + '\n')
            sys.print_exception(error, output)
    except OSError:
        print('Could not save last_error.log')

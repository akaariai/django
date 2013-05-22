#!/usr/bin/env python
#
# Run Django test suite in parallel
#
# Run it as: ./paralleltests.py --runners=<N> --settings=test_sqlite [test_labels ...]
#
# The optimal number of runners is probably the number of cores * 2


from subprocess import Popen
import os
import sys
import time

from runtests import ALWAYS_INSTALLED_APPS, SUBDIRS_TO_SKIP

MISSING_APPS = [
    'django.contrib.formtools',
    'django.contrib.webdesign',
    'django.contrib.sitemaps',
    'django.contrib.gis'
]


def parse_options(argv):
    opts = []
    labels = []
    n_runners = 1
    for arg in argv:
        if arg.startswith('--runners='):
            n_runners = int(arg.split('=')[1])
        elif arg.startswith('-'):
            opts.append(arg)
        else:
            labels.append(arg)
    # labels = ALWAYS_INSTALLED_APPS
    return n_runners, labels, opts


def discover_tests():
    test_labels = set([d for d in os.listdir(os.getcwd()) if
        os.path.isdir(d) and d != '__pycache__' and
        d not in SUBDIRS_TO_SKIP])
    return list(test_labels | set(MISSING_APPS))


def split_labels(n_runners, labels):
    for t in ALWAYS_INSTALLED_APPS:
        labels.append(t)

    groups = []
    for i in range(n_runners):
        groups.append([])
    for i, l in enumerate(labels):
        groups[i % n_runners].append(l)

    for g in groups:
        if 'model_inheritance_same_model_name' in g:
            g.remove('model_inheritance_same_model_name')
        if 'model_inheritance' in g:
            g.append('model_inheritance_same_model_name')

    return groups


def run_tests(groups, extra_opts):
    runners = []
    for g in groups:
        if len(g) == 0:
            continue
        cmd = ['./runtests.py'] + extra_opts + g
        runners.append(Popen(cmd))
        time.sleep(0.1)
    return runners


def wait_for_tests(runners):
    success = True

    while len(runners) > 0:
        time.sleep(0.1)
        for r in runners:
            exitcode = r.poll()
            if exitcode is not None:
                runners.remove(r)
                success = success and (exitcode == 0)
                break
    return success


def terminate_tests(runners):
    for r in runners:
        r.kill()


def run(n_runners, labels, extra_opts):
    if not labels:
        labels = discover_tests()
    groups = split_labels(n_runners, labels)

    runners = run_tests(groups, extra_opts)
    try:
        success = wait_for_tests(runners)
    except KeyboardInterrupt:
        terminate_tests(runners)
        success = False
    return success


if __name__ == '__main__':
    n_runners, labels, opts = parse_options(sys.argv[1:])
    success = run(n_runners, labels, opts)
    sys.exit(0 if success else -1)

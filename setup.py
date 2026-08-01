#!/usr/bin/env python
import io
import os
import re
from configparser import ConfigParser

from setuptools import setup

MODULE = 'cassini'
PREFIX = 'nantic'


def read(filename):
    return io.open(
        os.path.join(os.path.dirname(__file__), filename),
        'r', encoding='utf-8').read()


config = ConfigParser()
config.read('tryton.cfg')
info = dict(config.items('tryton'))
for key in ('depends', 'extras_depend', 'xml'):
    if key in info:
        info[key] = info[key].strip().splitlines()

version = info.get('version', '0.0.1')
major_version, minor_version, _ = version.split('.', 2)
major_version = int(major_version)
minor_version = int(minor_version)


def get_require_version(name):
    if minor_version % 2:
        require = '%s >= %s.%s.dev0, < %s.%s'
    else:
        require = '%s >= %s.%s, < %s.%s'
    return require % (
        name, major_version, minor_version,
        major_version, minor_version + 1)


requires = [get_require_version('trytond')]
for dependency in info.get('depends', []):
    if not re.match(r'(ir|res)(\W|$)', dependency):
        requires.append(get_require_version('trytond_%s' % dependency))

setup(
    name='%s_%s' % (PREFIX, MODULE),
    version=version,
    description='Server-stateful Cassini web client for Tryton',
    long_description=read('README'),
    author='NaN·tic',
    author_email='info@nan-tic.com',
    url='https://www.nan-tic.com/',
    package_dir={'trytond.modules.%s' % MODULE: '.'},
    packages=[
        'trytond.modules.%s' % MODULE,
        'trytond.modules.%s.tests' % MODULE,
        ],
    package_data={
        'trytond.modules.%s' % MODULE: (
            info.get('xml', [])
            + [
                'tryton.cfg', 'RNG_SUPPORT.md', 'tailwind.config.js',
                'locale/*.po', 'static/*', 'tests/tryton.cfg']),
        },
    install_requires=requires,
    zip_safe=False,
    entry_points="""
    [trytond.modules]
    %s = trytond.modules.%s
    """ % (MODULE, MODULE),
    test_suite='tests',
    test_loader='trytond.test_loader:Loader',
    tests_require=[get_require_version('proteus')],
    )

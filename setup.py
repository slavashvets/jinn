#!/usr/bin/env python

import sys
from setuptools import setup

setup(name='jinn',
      version='0.1.3',
      description='Jinn is a simple Jinja-based template processor. Similar to Ansible, but executes locally. Supports inheritance and extension of configs.',
      author='Slava Shvets',
      author_email='vyacheslav.shvets@t-systems.com',
      packages=['jinnlib'],
      scripts=['jinn.py'],
      python_requires='>=3.5',
      license='MIT',
      platforms='any',
      install_requires=[
        'Jinja2',
        'colorlog',
        'hvac',
        'pyyaml',
        'toolz',
        'docopt'],
      classifiers=["Operating System :: OS Independent",
                   'Programming Language :: Python :: 3.5',
                   'Programming Language :: Python :: 3.6',
                   'Programming Language :: Python :: 3.7',
                   ],
      )

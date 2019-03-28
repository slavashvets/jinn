#!/usr/bin/env python

"""
Upd v{version}

Usage:
    {program} [-d ] <profile> <path>
    {program} (-h | --help)

Options:
    <profile>                    Profile name
    <path>                       Path to base folder
    -d, --dump                   Dump merged YAML to review values
    -h, --help                   Show this screen and exit
"""

# built-in
from os.path import abspath
from os.path import basename
from os.path import dirname
from os.path import expanduser
from os.path import join
from sys import argv
from sys import stdout
import logging
import logging.handlers as handlers
import os
import pathlib
import yaml

# third-party
from jinnlib.dict_merge import dict_merge
from docopt import docopt
from toolz.dicttoolz import merge
import colorlog
import hvac
import jinja2

# key paths
__script_name__  = argv[0]                   # e.g. ../bin/thescript
__script_loc__   = abspath(__script_name__)  # e.g. /opt/scripts/thescript.py
__script_dir__   = dirname(__script_loc__)   # e.g. /opt/scripts
__home_dir__     = expanduser('~')           # e.g. /home/pupkin

# program information
__program__ = basename(__script_name__)      # e.g. thescript
__version__ = '0.0.1'

logger = logging.getLogger()

class Renderer(object):
  def __init__(self, base_path, output_path):
    self.base_path = base_path
    self.loader = jinja2.FileSystemLoader(
      searchpath="./"
    )
    self.env = jinja2.Environment(
      loader=self.loader,
      undefined=jinja2.StrictUndefined,
    )

  def render(self, **kwargs):
    for root, dirs, files in os.walk(self.base_path):
      root = pathlib.PurePosixPath(pathlib.Path(root))
      for f in files:
        template_file = root / f
        template = self.env.get_template(str(template_file))
        logger.info('Processing %s' % template_file)
        output_path = pathlib.Path('output').joinpath(template_file)
        output_path.parents[0].mkdir(parents=True, exist_ok=True)
        stream = template.stream(**kwargs)
        stream.dump(fp=str(output_path), errors='strict')

class NoProfileException(Exception):
  ...

def find_dict_keychain(d, target_key):
  """return a list of keys representing the path to target key in the dict
  """
  result = []
  for key, value in d.items():
    if target_key == key:
      result = [key]
      break
    if isinstance(value, dict):
      res = find_dict_keychain(value, target_key)
      if res:
        result = [key] + res
  return result

def build_profiles(path, profile):
  with open(path, 'r') as stream:
    p_dict = yaml.load(stream)
  result = find_dict_keychain(p_dict, profile)

  if not result:
    raise NoProfileException('No such profile "%s" in %s' % (profile, path))
  result = ['default'] + result
  logger.info("Profiles list: %s" % ','.join(result))
  return result

def setup_logger():
  handler = colorlog.StreamHandler()
  handler.setFormatter(colorlog.ColoredFormatter(
      '%(asctime)s %(bold)s%(log_color)s%(levelname)s %(reset)s%(message)s',
      reset=True))
  handler.setLevel(logging.DEBUG)

  logger.addHandler(handler)
  logger.setLevel(logging.INFO)

def main():
  setup_logger()
  args = docopt(__doc__.format(program=__program__, version=__version__),
                version=__version__)

  try:
    profiles = build_profiles('profiles.yaml', args['<profile>'])
  except NoProfileException as e:
    logger.fatal(e)
    exit(1)

  config = {}
  for profile in profiles:
    path = "config/%s.yaml" % profile
    try:
      with open(path, 'r') as stream:
        dict_merge(config, yaml.load(stream))
    except FileNotFoundError as e:
      logger.warning("%s doesn't exist. Skip..." % path)

  vault_client = hvac.Client(
    url=os.environ['VAULT_ADDR'],
    token=os.environ['VAULT_TOKEN'],
  )

  def vault_wrapper(path):
    return vault_client.read(path)['data']

  if args['--dump']:
    logger.info("Printing merged config values:")
    yaml.dump(config, stdout, default_flow_style=False)
    exit(0)

  renderer = Renderer(args['<path>'], "output")
  renderer.render(**config, vault=vault_wrapper, profile=args['<profile>'])

if __name__ == "__main__":
  main()

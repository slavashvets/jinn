#!/usr/bin/env python

"""
Jinn v{version}

Usage:
    {program} [-o DIR] <path>
    {program} [-d ] [-o DIR] <profile> <path>
    {program} (-h | --help)

Options:
    <profile>                    Profile name
    <path>                       Path to base folder
    -o DIR, --output DIR         Output directory
    -d, --dump                   Dump merged YAML to review values
    -h, --help                   Show this screen and exit
"""

# built-in
from os.path import abspath
from os.path import basename
from os.path import dirname
from os.path import expanduser
from os.path import join
from os.path import isfile
from os import listdir
from sys import argv
from sys import stdout
import logging
import logging.handlers as handlers
import os
import stat
import pathlib
import yaml
import re
import pathspec 

# third-party
from jinnlib.dict_merge import dict_merge
from jinnlib import __version__
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

logger = logging.getLogger()

def remove_prefix(path, prefix):
    path_str = str(path)
    prefix_str = str(prefix)

    if not prefix_str.endswith('/'):
      prefix_str += '/'
    return path_str[len(prefix_str):] if path_str.startswith(prefix_str) else path_str

def finalize(value):
  if value == None:
    raise Exception("None value is not allowed")
  else:
    return value

class Renderer(object):
  def __init__(self, base_path, output_path):
    self.base_path = pathlib.Path(base_path)
    if output_path is not None:
      self.output_path = output_path
    else:
      self.output_path = pathlib.Path('output') / self.base_path.parts[-1]
    self.loader = jinja2.FileSystemLoader(
      searchpath="./"
    )
    self.env = jinja2.Environment(
      finalize=finalize,
      loader=self.loader,
      undefined=jinja2.StrictUndefined,
    )

  def render(self, **kwargs):
    def get_list_files_function(folder):
      def list_files(path):
        path = pathlib.Path(folder) / path
        if not path.is_dir() or not path.exists():
          raise Exception("%s directory doesn't exist" % path)
        result = []
        for root, dirs, files in os.walk(path):
          root = pathlib.PurePosixPath(pathlib.Path(root))
          for f in files:
            f = root / f
            result.append(str(f))
        return result
      return list_files

    spec = None
    if pathlib.Path(self.base_path / '.jinnignore').is_file():
      with open(self.base_path / '.jinnignore', 'r') as fh:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', fh)

    for root, dirs, files in os.walk(self.base_path):
      root = pathlib.PurePosixPath(pathlib.Path(root))
      for f in files:
        # If .jinnignore file found and filepath matches expressions then we will ignore file
        if spec and spec.match_file(remove_prefix(root / f, self.base_path)):
          continue

        template_file = root / f
        template = self.env.get_template(str(template_file))
        logger.info('Processing %s' % template_file)
        output_template_path = pathlib.Path(*template_file.parts[1:])
        template_folder = template_file.parents[0]
        output_path = pathlib.Path(self.output_path).joinpath(output_template_path)
        output_path.parents[0].mkdir(parents=True, exist_ok=True)
        stream = template.stream(
          **kwargs,
          list_files=get_list_files_function(template_folder))
        stream.dump(fp=str(output_path), errors='strict')

        # Inherit executable flag to the output file
        if os.access(template_file, os.X_OK):
          logger.debug("Set executable flag to %s" % output_path)
          st = os.stat(output_path)
          os.chmod(output_path, st.st_mode | stat.S_IEXEC)

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
    p_dict = yaml.safe_load(stream)
  result = find_dict_keychain(p_dict, profile)

  if not result:
    raise NoProfileException('No such profile "%s" in %s' % (profile, path))
  result = ['default'] + result + ['lock']
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

def dict_format(dct: dict, format_kwargs: dict):
  """ Loop over nested dict values and format all strings.

  :param dct: dict for updating
  :param format_kwargs: key-value arguments to pass to format fuction
  :return: None
  """
  for k, v in dct.items():
    if isinstance(v, dict):
      dict_format(v, format_kwargs)
    elif isinstance(v, str):
      dct[k] = v.format(**format_kwargs)

def main():
  setup_logger()
  args = docopt(__doc__.format(program=__program__, version=__version__),
                version=__version__)
  config = {}

  if args['<profile>']:
    try:
      profiles = build_profiles('profiles.yaml', args['<profile>'])
    except NoProfileException as e:
      logger.fatal(e)
      exit(1)

    config['profile'] = args['<profile>']

    for profile in profiles:
      path = "config/%s.yaml" % profile
      try:
        with open(path, 'r') as stream:
          dict_merge(config, yaml.safe_load(stream))
      except FileNotFoundError as e:
        logger.warning("%s doesn't exist. Skip..." % path)
    dict_format(config, {
        "profile": args['<profile>'],
        "profile_num": re.sub("\D", "", args['<profile>']),
    })

    if 'profiles' not in config.keys():
      config['profiles'] = profiles

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

  renderer = Renderer(args['<path>'], args['--output'])
  renderer.render(**config,
    vault=vault_wrapper,
    env=os.environ,
  )

if __name__ == "__main__":
  main()

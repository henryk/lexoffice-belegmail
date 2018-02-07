#!/usr/bin/env python3
import logging
import argparse
import multiprocessing
import pprint

from .config import ConfigurationManager
from .mail import ImapReceiver


logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('-m', '--mode', choices=["daemon", "debug"], default="daemon", help="Execution mode")
	parser.add_argument('config_yaml', nargs='+', type=argparse.FileType('r'), help="Configuration file(s) in YAML format")

	args = parser.parse_args()

	c = ConfigurationManager()
	for fp in args.config_yaml:
		c.load(fp)

	if args.mode == "daemon":
		subprocesses = []
		for configuration in c.configurations():
			i = ImapReceiver(configuration)
			subprocesses.append( multiprocessing.Process(target=i.run) )

		for p in subprocesses:
			p.start()

		for p in subprocesses:
			p.join()
	else:
		pprint.pprint(c.configs)

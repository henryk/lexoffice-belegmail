#!/usr/bin/env python3
import logging
import argparse
import multiprocessing
import pprint

from .config import ConfigurationManager
from .mail import ImapReceiver
from .atos_cc import CreditScraperManager
from .cc_sync import FinancialAccountManager
from .lexoffice import RestClient


logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True
logging.getLogger("chardet.charsetprober").setLevel(logging.WARNING)

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('-m', '--mode', choices=["daemon", "fetch_credit", "fetch_transactions", "debug_config"], default="daemon", help="Execution mode")
	parser.add_argument('config_yaml', nargs='+', type=argparse.FileType('r'), help="Configuration file(s) in YAML format")

	args = parser.parse_args()

	c = ConfigurationManager()
	for fp in args.config_yaml:
		c.load(fp)

	if args.mode == "daemon":
		subprocesses = []
		for configuration in c.configurations():
			i = ImapReceiver(configuration)
			subprocesses.append( multiprocessing.Process(target=i.run, name="Worker-{0}".format(configuration.name)) )

		for p in subprocesses:
			p.start()

		for p in subprocesses:
			p.join()

	elif args.mode == "fetch_credit":
		for configuration in c.configurations():
			if 'atos_cc' in configuration:
				m = CreditScraperManager(configuration)
				with m:
					for c in m.all_cards():
						print(c)
						c.synchronize_csv()

	elif args.mode == "fetch_transactions":
		for configuration in c.configurations():
			m = FinancialAccountManager(configuration)
			for account in m.all_accounts():
				print(account)
				pprint.pprint(m.c.get_financial_transactions(financial_account_id=account.financial_account_id))

	else:
		pprint.pprint(c.configs)

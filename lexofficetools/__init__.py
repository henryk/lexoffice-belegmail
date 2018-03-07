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
	parser.add_argument('-m', '--mode', choices=["daemon", "fetch_credit", "fetch_transactions", "sync_credit", "debug_config"], default="daemon", help="Execution mode")
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
			if 'cc' in configuration:
				m = CreditScraperManager(configuration)
				with m:
					for c in m.all_cards():
						print(c)
						c.synchronize_csv()

	elif args.mode == "fetch_transactions":
		for configuration in c.configurations():
			m = FinancialAccountManager(configuration)
			m.fetch_accounts()
			for account in m.all_accounts():
				print(account)
				if account.financial_account_id:
					pprint.pprint(m.c.get_financial_transactions(financial_account_id=account.financial_account_id))

	elif args.mode == "sync_credit":
		for configuration in c.configurations():
			if 'cc' in configuration:
				f = FinancialAccountManager(configuration)
				f.fetch_accounts()

				m = CreditScraperManager(configuration)
				with m:
					for c in m.all_cards():
						account = f.get(c.card_no, None)
						if account is not None:
							account.update(card_no=c.card_no)

						c.synchronize_statements(f.c)
						c.synchronize_csv()


				for account in f.all_accounts():
					if account.type_ == 'creditcard' and account.card_no is not None:
						f.sync_credit_transactions(account, m.get_transactions(account.card_no))

	else:
		pprint.pprint(c.configs)

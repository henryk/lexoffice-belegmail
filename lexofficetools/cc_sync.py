
from .lexoffice import RestClientUser
from .utils import CardNumber, symmetric_difference
import pprint
import csv
import io
import datetime
import time

def rename(d):
	mapping={"type": "type_", "financialAccountId": "financial_account_id"}
	for k,v in mapping.items():
		if k in d:
			d[v] = d.pop(k)
	return d

class Account(object):
	def __init__(self, **kwargs):
		kwargs = rename(kwargs)
		self._card_no = None

		self.financial_account_id=kwargs.pop("financial_account_id", None)
		self.card_no=kwargs.pop("card_no", None)
		self.name=kwargs.pop("name", None)
		self.type_=kwargs.pop("type_", None)
		self.extra=kwargs

	def __str__(self):
		return "{0}(financial_account_id={1!r}, card_no={2!r}, name={3!r}, type_={4!r})".format(
			self.__class__.__name__,
			self.financial_account_id,
			self.card_no,
			self.name,
			self.type_
		)

	def update(self, **kwargs):
		kwargs = rename(kwargs)

		for i in ['financial_account_id', 'name', 'card_no', 'type_']:
			if i in kwargs:
				setattr(self, i, kwargs.pop(i))
		self.extra.update(kwargs)

	@property
	def card_no(self):
		return self._card_no

	@card_no.setter
	def card_no(self, value):
		if value is None:
			self._card_no = value
		else:
			if self._card_no is None:
				self._card_no = CardNumber.coerce(value)
			else:
				self._card_no.update(value)


class FinancialAccountManager(RestClientUser):
	def __init__(self, configuration):
		super(FinancialAccountManager, self).__init__(configuration)
		self._accounts = []

	def fetch_accounts(self):
		if 'cc' in self.config:
			for credit_config in self.config['cc']:
				if 'cards' in credit_config:
					if isinstance(credit_config['cards'], dict):
						for card, name in credit_config['cards'].items():
							self._accounts.append(Account(name=name, card_no=card))

					else:
						for card in credit_config['cards']:
							self._accounts.append(Account(card_no=card))


		self.ensure_login()
		for account in self.c.list_financial_accounts():
			a = None

			a = self.get(account['financialAccountId'], None)

			if a is None and 'name' in account:
				a = self.get(account['name'], None)

			if a is None:
				a = Account(**account)
				self._accounts.append(a)
			else:
				a.update(**account)

	def all_accounts(self):
		for account in self._accounts:
			yield account

	def get(self, search, default=Ellipsis):
		for account in self._accounts:

			if isinstance(search, CardNumber):
				if account.card_no == search:
					return account
			else:
				if account.financial_account_id==search:
					return account
				elif account.name==search:
					return account
				elif account.card_no==search:
					return account

		if default is Ellipsis:
			raise KeyError
		else:
			return default

	def sync_credit_transactions(self, account, transactions):
		old_transactions = self.c.get_financial_transactions(financial_account_id=account.financial_account_id)

		def transform_a(item):
			return  (item.purchaseDate, item.signed_amount, item.mainDescription, item.additionalDescription)

		def transform_b(item):
			if '/' in item['purpose']:
				description_a = item['purpose'].rsplit('/', 1)[0].strip()
				description_b = item['purpose'].rsplit('/', 1)[1].strip()
			else:
				description_a = item['purpose'].strip()
				description_b = ''

			amount = "{0:+.2f}".format( item['amount'] ).replace('.', ',')

			date = item['dateLocalized'] # FIXME

			return (date, amount, description_a, description_b)

		missing, old = symmetric_difference(transactions, old_transactions, transform_a=transform_a, transform_b=transform_b)

		if len(missing):
			self.upload_credit_transactions(account, missing)

	def upload_credit_transactions(self, account, transactions):
		## Der Flow ist folgendermaßen:
		##  File hochladen, id bekommen
		##  Import-Settings für den Account mit PUT setzen (für *alle* Imports in diesen Account)
		##  Import anstoßen, Import-ID bekommen
		##  Import-Ende pollen, Antwort auswerten

		with io.StringIO() as fp:
			writer = csv.writer(fp, delimiter=";")
			for transaction in transactions:
				purpose = transaction.mainDescription.strip()
				if transaction.additionalDescription.strip():
					purpose = "{0} / {1}".format(purpose, transaction.additionalDescription.strip())

				writer.writerow( 
					[account.card_no,
						transaction.postingDate,
						transaction.purchaseDate,
						purpose,
						"", "",   # Fremdwährung und Kurs
						transaction.signed_amount]
				)

				csv_data = fp.getvalue().encode("UTF-8")

		filename = "Kreditkartenumsätze_{0}_{1:%Y-%m-%d_%H-%M-%S}.csv".format(str(account.card_no)[-4:], datetime.datetime.utcnow())
		response = self.c.upload_csv_data(filename, csv_data)

		if not 'id' in response:
			raise IOError("Unerwartete Antwort von der Upload-API: {0}".format(pprint.pformat(response)))

		upload_id = response['id']

		## Fixe Import-Settings
		settings = {
			"characterSet": "UTF-8",
			"delimiter": "Semicolon",
			"quoteCharacter": "DoubleQuote",
			"negateAmount": False,
			"fieldMappings": [
				{"columnIndex": 2, "fieldName": "ValueDate"},
				{"columnIndex": 3, "fieldName": "Purpose"},
				{"columnIndex": 6, "fieldName": "Amount"},
			]
		}
		
		response = self.c.csv_preview(upload_id)

		response = self.c.put_importprofile(account, settings)
		if not response.get("statusType", "") == "OK":
			raise IOError("Unerwartete Antwort von der Import-Profil-API: {0}".format(pprint.pformat(response)))

		response = self.c.do_import(account, upload_id, filename)
		if response.get('status', '') not in ("PENDING", "DONE"):
			raise IOError("Unerwartete Antwort von der Import-API: {0}".format(pprint.pformat(response)))

		for i in range(10):
			if response.get('status', '') == "DONE":
				break

			time.sleep(3)
			response = self.c.get_importstate(response['financialTransactionImportId'])
			
			if response.get('status', '') not in ("PENDING", "DONE"):
				raise IOError("Unerwartete Abschluss-Antwort von der Import-API: {0}".format(pprint.pformat(response)))

		return response.get('status', '')

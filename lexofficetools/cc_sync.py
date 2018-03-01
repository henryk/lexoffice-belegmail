
from .lexoffice import RestClientUser
from .utils import CardNumber

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
		print(transactions)

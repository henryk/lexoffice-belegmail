
from .lexoffice import RestClientUser

def rename(d):
	mapping={"type": "type_", "financialAccountId": "financial_account_id"}
	for k,v in mapping.items():
		if k in d:
			d[v] = d.pop(k)
	return d

class Account(object):
	def __init__(self, **kwargs):
		kwargs = rename(kwargs)

		self.financial_account_id=kwargs.pop("financial_account_id", None)
		self.name=kwargs.pop("name", None)
		self.type_=kwargs.pop("type_", None)
		self.extra=kwargs

	def __str__(self):
		return "{0}(financial_account_id={1!r}, name={2!r}, type_={3!r})".format(
			self.__class__.__name__,
			self.financial_account_id,
			self.name,
			self.type_
		)

	def update(self, **kwargs):
		kwargs = rename(kwargs)

		for i in ['financial_account_id', 'name', 'type_']:
			if i in kwargs:
				setattr(self, i, kwargs.pop(i))
		self.extra.update(kwargs)

class FinancialAccountManager(RestClientUser):
	def __init__(self, configuration):
		super(FinancialAccountManager, self).__init__(configuration)
		self._accounts = []

	def all_accounts(self):
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

		for account in self._accounts:
			yield account

	def get(self, search, default=Ellipsis):
		for account in self._accounts:
			if account.financial_account_id==search:
				return account
			elif account.name==search:
				return account

		if default is Ellipsis:
			raise KeyError
		else:
			return default

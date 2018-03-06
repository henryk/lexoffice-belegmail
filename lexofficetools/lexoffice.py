import requests
import json
import os.path

URLS = {
	'login': 'https://{lexofficeInstance}/grld-public/login/authorize',
	'logout': 'https://{lexofficeInstance}/grld-public/login/v100/logout',
	'privilege': 'https://{lexofficeInstance}/grld-rest/privilege-management/v100/privilege',
	'uploadBookkeepingVoucherImage': 'https://{lexofficeInstance}/grld-rest/voucherimageservice/1/v101/uploadBookkeepingVoucherImage/',
	'financialAccounts': 'https://{lexofficeInstance}/grld-rest/financialaccountservice/v100/financialAccounts',
	'financialTransactions': 'https://{lexofficeInstance}/grld-rest/financialtransactionservice/v100/financialTransactions',
	'uploadCsvFile': 'https://{lexofficeInstance}/grld-upload-rest/uploadNtService/v100/uploadCsvFile/',
	'put_importprofile': 'https://{lexofficeInstance}/grld-rest/importprofileservice/v100/importprofile/financialAccount/{financial_account_id}',
	'import': 'https://{lexofficeInstance}/grld-rest/financialtransactionimportservice/v100/import',
	'get_importstate': 'https://{lexofficeInstance}/grld-rest/financialtransactionimportservice/v100/importState/{financial_transaction_import_id}',
	'csvPreview': 'https://{lexofficeInstance}/grld-rest/financialtransactionimportservice/v100/csvPreview',
}

USER_AGENT = 'GITHUB_COM_HENRYK_LEXOFFICE_BELEGMAIL/43'

class RestClientUser(object):
	def __init__(self, configuration):
		self.c = None
		self.config = configuration

	def ensure_login(self):
		# FIXME Better logic
		if not self.c:
			self.c = RestClient(self.config)
			self.c.login()


class RestClient(object):
	def __init__(self, configuration):
		self.config = configuration
		self.session = None

	def ensure_session(self):
		if not self.session:
			self.session = requests.Session()
			self.session.headers.update({'User-Agent': USER_AGENT})

	def get_url(self, endpoint, **kwargs):
		values = dict(**self.config)
		values.update(kwargs)
		return URLS[endpoint].format(**values)

	def json_api_post(self, endpoint, params):
		self.ensure_session()
		r = self.session.post(self.get_url(endpoint), json=params)
		r.raise_for_status()
		return r.json()

	def json_api_get(self, endpoint, params=None, url_params={}):
		self.ensure_session()
		r = self.session.get(self.get_url(endpoint, **url_params), params=params)
		r.raise_for_status()
		return r.json()

	def json_api_put(self, endpoint, params, url_params={}):
		self.ensure_session()
		r = self.session.put(self.get_url(endpoint, **url_params), json=params)
		r.raise_for_status()
		return r.json()

	def json_api_multipart(self, endpoint, params):
		self.ensure_session()
		r = self.session.post(self.get_url(endpoint), files=params)
		r.raise_for_status()
		return r.json()

	def login(self):
		return self.json_api_post('login', self.config['lexoffice']['auth'])

	def logout(self):
		return self.json_api_get('logout')

	def privilege(self):
		return self.json_api_get('privilege')

	def upload_image(self, filename, data = None, content_type='application/octet-stream'):
		if not data:
			with open(filename, "rb") as fp:
				data = fp.read()

		params = {
			"file": (os.path.basename(filename), data, content_type),
			"uploadType": (None, 'voucher', 'text/plain;charset=ISO-8859-1'),
		}
		return self.json_api_multipart('uploadBookkeepingVoucherImage', params)

	def upload_csv_data(self, filename, data, content_type='application/vnd.ms-excel'):
		params = {
			"file": (os.path.basename(filename), data, content_type),
			"uploadType": (None, 'csv', None),
		}
		return self.json_api_multipart('uploadCsvFile', params)

	def put_importprofile(self, account, settings):
		return self.json_api_put('put_importprofile', settings, {'financial_account_id': account.financial_account_id})

	def get_importstate(self, financial_transaction_import_id):
		return self.json_api_get('get_importstate', url_params={'financial_transaction_import_id': financial_transaction_import_id})

	def csv_preview(self, file_id):
		params = {
			"fileId": file_id,
			"delimiter": "Semicolon",
			"quoteCharacter": "DoubleQuote",
			"characterSet": "UTF-8",
			"negateAmount": False,
		}
		return self.json_api_post('csvPreview', params)

	def do_import(self, account, file_id, description):
		params = {
			"fileId": file_id,
			"financialAccount": {
				"financialAccountId": account.financial_account_id,
				"name": account.name,
			},
			"description": description,
		}
		return self.json_api_post('import', params)

	def list_financial_accounts(self):
		return self.json_api_get('financialAccounts')

	def get_financial_transactions(self, first_row=0, num_rows=60, search_state=None, financial_account_id=None):
		params = {
			"firstRow": first_row,
			"numRows": num_rows,
		}
		if search_state is not None:
			params['searchState'] = search_state
		if financial_account_id is not None:
			params['financialAccountId'] = financial_account_id
		return self.json_api_get('financialTransactions', params)

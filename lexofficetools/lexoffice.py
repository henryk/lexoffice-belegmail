import requests
import json
import os.path

URLS = {
	'login': 'https://{lexofficeInstance}/grld-public/login/authorize',
	'privilege': 'https://{lexofficeInstance}/grld-rest/privilege-management/v100/privilege',
	'uploadBookkeepingVoucherImage': 'https://{lexofficeInstance}/grld-rest/voucherimageservice/1/v101/uploadBookkeepingVoucherImage/',
}

USER_AGENT = 'GITHUB_COM_HENRYK_LEXOFFICE_BELEGMAIL/43'

class RestClient(object):
	def __init__(self, configuration):
		self.config = configuration
		self.session = None

	def ensure_session(self):
		if not self.session:
			self.session = requests.Session()
			self.session.headers.update({'User-Agent': USER_AGENT})

	def get_url(self, endpoint):
		return URLS[endpoint].format(**self.config)

	def json_api_post(self, endpoint, params):
		self.ensure_session()
		r = self.session.post(self.get_url(endpoint), json=params)
		r.raise_for_status()
		return r.json()

	def json_api_get(self, endpoint):
		self.ensure_session()
		r = self.session.get(self.get_url(endpoint))
		r.raise_for_status()
		return r.json()

	def json_api_multipart(self, endpoint, params):
		self.ensure_session()
		r = self.session.post(self.get_url(endpoint), files=params)
		r.raise_for_status()
		return r.json()

	def login(self):
		return self.json_api_post('login', self.config['lexoffice']['auth'])

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

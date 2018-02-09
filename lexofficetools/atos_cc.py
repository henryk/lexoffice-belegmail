import requests
import contextlib
from contextlib import contextmanager
from urllib.parse import urljoin
import pprint

from bs4 import BeautifulSoup, NavigableString, Comment

ENTRY_URLS = {
	## Some via http://ipv4info.com/domains-in-block/s98ddec/89.106.184.0-89.106.191.255.html

	# Berliner Sparkasse
	'bspk': 'https://kreditkarten-banking.berliner-sparkasse.de/cas/dispatch.do?bt_PRELON=do&ref=BSPK&service=COS',

	# BW|Bank
	'bwbank': 'https://www.kreditkartenbanking.de/ssc/cas/dispatch.do?bt_PRELON=1&ref=2000_SSC&service=COS',

	# Amazon
	'amazon': 'https://kreditkarten-banking.lbb.de/Amazon/cas/dispatch.do?bt_PRELON=do&ref=1200_AMAZON&service=COS',

	# Commerzbank
	'commerzbank': 'https://www.kreditkartenbanking.de/businesscard/cas/dispatch.do?bt_PRELON=1&ref=1500_CHAM&service=COS',

	# Bahncard
	'bahncard': 'https://www.kreditkartenbanking.de/bahncard/cas/dispatch.do?bt_PRELON=1&ref=1500_KROKO&service=COS',

	# Postbank
	'postbank': 'https://kreditkarten.postbank.de/cas/dispatch.do?bt_PRELON=1&ref=1300&service=MASTER',
}

class LoginError(Exception): pass

class CreditAccountScraper(object):
	def __init__(self, configuration):
		self.config = configuration
		self.clear_session()

	@property
	def session(self):
		if not self._session:
			self._session = requests.session()
		return self._session

	@property
	def soup(self):
		return BeautifulSoup(self.current_page.content, 'lxml')

	def navigate(self, url):
		self.current_page = self.session.get( self.resolve_url(url) )

	def clear_session(self):
		self._session = None
		self.current_page = None

	def resolve_url(self, url):
		if self.current_page:
			return urljoin(self.current_page.url, url)
		else:
			return url

	def submit_form(self, form_name, data, submit_name):
		form = self.soup.body.find('form', attrs={'name': form_name})
		action = self.resolve_url(form['action'])
		request_data = {}

		for i_elem in form.find_all('input'):
			i_type = i_elem.get('type', '').lower()
			i_name = i_elem.get('name', i_elem.get('id', ''))
			if i_type == 'hidden':
				request_data[i_name] = i_elem['value']
			elif i_type in ('text', 'password'):
				request_data[i_name] = data[i_name]
			elif i_type == 'submit' and i_name == submit_name:
				request_data[i_name] = i_elem['value']

		self.current_page = self.session.post(action, data=request_data)

	def log_in(self):
		self.navigate( ENTRY_URLS[self.config['bank']] )

		self.submit_form('preLogonForm', self.config['auth'], 'bt_LOGON')
		
		error_tab = self.soup.body.find('td', attrs={'class': 'tabError'})
		if error_tab:
			raise LoginError(
				", ".join(
					e.strip() for e in
					error_tab.find_all(string=True, recursive=True)
					if e.strip() != ""
				)
			)
		if self.soup.body.find('form', attrs={'name': 'preLogonForm'}):
			raise LoginError('Login fehlgeschlagen, keine weitere Information verfügbar.')

		self.submit_form('service', {}, 'continueBtn')

	def log_out(self):
		if self.current_page:
			a_logout = self.soup.body.find('a', attrs={'id': 'nav.logout'})
			self.navigate(a_logout['href'])
			self.clear_session()

	def fetch_all(self):
		print(self.soup.prettify())

	@contextmanager
	def logged_in(self):
		self.log_in()
		try:
			yield
		finally:
			self.log_out()

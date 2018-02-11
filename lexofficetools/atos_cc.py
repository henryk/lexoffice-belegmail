import requests
import contextlib
from contextlib import contextmanager
from urllib.parse import urljoin
import pprint

from bs4 import BeautifulSoup, NavigableString, Comment, Tag

DBG_counter = None
def _DBG_out(data):
	global DBG_counter
	if DBG_counter is not None:
		with open('DBG_{0:04d}.txt'.format(DBG_counter), 'w') as fp:
			fp.write(data)
		DBG_counter = DBG_counter + 1


CREDIT_ENTRY_URLS = {
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

class LoggedInMixin(object):
	@contextmanager
	def logged_in(self):
		self.log_in()
		try:
			yield
		finally:
			self.log_out()

class CreditScraperManager(object):
	def __init__(self, configuration):
		self.config = configuration
		self.login_stack = None

	def __enter__(self):
		if self.login_stack is not None:
			raise Exception("CreditScraperManager may not nest")
		else:
			self.login_stack = []

	def __exit__(self, type, value, tb):
		while self.login_stack:
			try:
				self.login_stack.pop().log_out()
			except:
				pass # FIXME
		self.login_stack = None
		return False

	def _login_push(self, obj):
		try:
			obj.log_in()
			self.login_stack.append(obj)
		except:
			raise

	def _logout_pop(self):
		self.login_stack.pop().log_out()


	def all_cards(self):
		if self.login_stack is None:
			raise Exception("Must enter CreditScraperManager context first")

		for c in self.config['atos_cc']: ## FIXME Card filter
			if 'sso' in c:
				if c['sso'] == 'bspk':
					outer = SparkasseCreditLogin(c)
					self._login_push(outer)
					inner = outer.cc_sso()
					self._login_push(inner)
					yield from inner.enumerate_cards()
					self._logout_pop()
					self._logout_pop()

			elif 'bank' in c:
				s = CreditAccountScraper(c)
				self._login_push(s)
				yield from s.enumerate_cards()
				self._logout_pop()

class ScraperBase(object):
	def __init__(self, configuration, parent=None):
		self.config = configuration
		self.parent = parent
		self.clear_session()
		if parent:
			self.current_page = parent.current_page

	@property
	def session(self):
		if self.parent:
			return self.parent.session
		if not self._session:
			self._session = requests.session()
		return self._session

	@property
	def soup(self):
		return BeautifulSoup(self.current_page.content, 'lxml')

	def navigate(self, url):
		self.current_page = self.session.get( self.resolve_url(url) )
		
		_DBG_out(self.soup.prettify())

	def clear_session(self):
		self._session = None
		self.current_page = None

	def resolve_url(self, url):
		if self.current_page:
			return urljoin(self.current_page.url, url)
		else:
			return url

	def submit_form(self, form_attrs, data, submit_name, postprocess_callback=None):
		if isinstance(form_attrs, Tag):
			form = form_attrs
		else:
			form = self.soup.body.find('form', attrs=form_attrs)

		action = self.resolve_url(form['action'])
		request_data = {}

		_DBG_out(self.soup.prettify())

		if callable(data):
			data_callback = data
		else:
			data_callback = lambda name, form, element: data[name]

		for i_elem in form.find_all('input'):
			i_type = i_elem.get('type', '').lower()
			i_name = i_elem.get('name', i_elem.get('id', ''))
			
			if i_type == 'hidden':
				request_data[i_name] = i_elem['value']
			
			elif i_type in ('text', 'password'):

				try:
					request_data[i_name] = data_callback(i_name, form, i_elem)
				except KeyError:
					request_data[i_name] = i_elem.get('value', None)
					if request_data[i_name] is None:
						raise

			elif i_type == 'submit' and i_name == submit_name:
				request_data[i_name] = i_elem['value']

			elif i_type in ('checkbox', 'radio'):
				if i_elem.get('checked', None) is not None and i_elem.get('value', None) is not None:
					request_data[i_name] = i_elem['value']

			elif i_type == 'select':
				options = i_elem.find_all('option')
				for option in option:
					if option.get('selected', None) is not None and option.get('value', None) is not None:
						request_data[i_name] = option['value']


		if postprocess_callback:
			if isinstance(postprocess_callback, (list, tuple)):
				for cb in postprocess_callback:
					cb(request_data, form)
			else:
				postprocess_callback(request_data, form)

		_DBG_out(pprint.pformat(request_data))

		self.current_page = self.session.post(action, data=request_data)

		_DBG_out(self.soup.prettify())

def simplify_message(element):
	return ", ".join(
				e.strip() for e in
				element.find_all(string=True, recursive=True)
				if e.strip() != ""
			)

class CreditAccountScraper(ScraperBase, LoggedInMixin):

	def log_in(self):
		self.navigate( CREDIT_ENTRY_URLS[self.config['bank']] )

		self.submit_form({'name': 'preLogonForm'}, self.config['auth'], 'bt_LOGON')
		
		error_tab = self.soup.body.find('td', attrs={'class': 'tabError'})
		if error_tab:
			raise LoginError(simplify_message(error_tab))
		if self.soup.body.find('form', attrs={'name': 'preLogonForm'}):
			raise LoginError('Login fehlgeschlagen, keine weitere Information verfügbar.')

		self.submit_form({'name': 'service'}, {}, 'continueBtn')

	def log_out(self):
		if self.current_page:
			a_logout = self.soup.body.find('a', attrs={'id': 'nav.logout'})
			self.navigate(a_logout['href'])
			self.clear_session()

	def enumerate_cards(self):
		for a_elem in self.soup.find('table', attrs={'id': 'account'}).find_all('a'):
			if a_elem.get('id', '').startswith('rai-') and a_elem.get('href', None) is not None:
				yield CardDataScraper(self.config, self, a_elem)

class CardDataScraper(ScraperBase):
	def __init__(self, configuration, parent, a_elem):
		super(CardDataScraper, self).__init__(configuration, parent)
		self._navigated = False
		self._a_elem = a_elem

	def _ensure_navigation(self):
		if not self._navigated:
			self.navigate(self._a_elem['href'])
			self._navigated = True

	@property
	def card_no(self):
		return "".join( "".join( self._a_elem.stripped_strings ).split() )

	def __repr__(self):
		return "<CardDataScraper(card_no={0!r}>".format(self.card_no)

def last_submit(request_data, form):
	submit_name = None
	submit_value = None
	for i_elem in form.find_all('input'):
		i_type = i_elem.get('type', '').lower()
		i_name = i_elem.get('name', i_elem.get('id', ''))
		if i_type == 'submit':
			submit_name = i_name
			submit_value = i_elem['value']
	if submit_name is None:
		raise LoginError("Kann submit-Feld nicht finden: {0}".format(form))
	else:
		request_data[submit_name] = submit_value

def authid_pin_filler(config):
	def callback(name, form, element):
		if element.get('type', '').lower() == 'text' and element.get('disabled', None) is None:
			return config['auth_id']
		elif element.get('type', '').lower() == 'password':
			return config['pin']
		raise KeyError('Not matched')
	return callback

def select_first_option(request_data, form):
	for select in form.find_all('select'):
		option = None
		for option in select.find_all('option'):
			pass
		if option:
			request_data[select['name']] = option['value']



class SparkasseCreditLogin(ScraperBase, LoggedInMixin):
	KREDITKARTE_BASE = "https://www.berliner-sparkasse.de/de/home/onlinebanking/finanzstatus/kreditkarten/details.html"

	def log_in(self):
		self.navigate( self.KREDITKARTE_BASE )

		self.submit_form({'autocomplete': 'off'}, authid_pin_filler(self.config['auth']), None, last_submit)

		error_div = self.soup.body.find('div', attrs={'class': 'msgerror'})
		if error_div:
			raise LoginError(simplify_message(error_div))

	def log_out(self):
		if self.current_page:
			form = self.soup.body.find('div', class_='loginlogout').find('form')
			self.submit_form(form, {}, None, last_submit)
			self.clear_session()

	def cc_sso(self):
		# Simple way: Select and choose the first form with select field, choose last credit card
		form = self.soup.body.find('select').find_parent('form')
		self.submit_form(form, {}, None, [select_first_option, last_submit])

		return SparkasseCreditScraper(self.config, self)

class SparkasseCreditScraper(CreditAccountScraper):
	def __init__(self, configuration, parent):
		super(SparkasseCreditScraper, self).__init__(configuration, parent)
		self.sso_a = None
		for a in self.soup.body.find('select').find_parent('form').find_all('a'):
			if '/sso' in a['href']:
				self.sso_a = a

	def log_in(self):
		assert self.sso_a
		self.navigate(self.sso_a['href'])
		self.submit_form({'name': 'submitForm'}, {}, 'continueBtn')


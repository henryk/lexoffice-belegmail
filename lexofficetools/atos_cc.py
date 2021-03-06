import requests
import contextlib
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import pprint
import re
import csv
import collections
from datetime import datetime, timezone
import os, os.path


from bs4 import BeautifulSoup, NavigableString, Comment, Tag

from .utils import CardNumber, LoginError, normalize_date_TTMMJJJJ, symmetric_difference
from .utils import DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_CSV, CARD_STATEMENT_CSV, CARD_STATEMENT_PDF

DBG_counter = None
def _DBG_out(data):
	global DBG_counter
	if DBG_counter is not None:
		with open('DBG_{0:04d}.txt'.format(DBG_counter), 'w') as fp:
			fp.write(data)
		DBG_counter = DBG_counter + 1

TRANSACTION_FIELD_NAMES = ('card_no', 'signed_amount', 'ref', 'rai', 'amount', 'postingSequence', 'postingDate', 'statementId', 'formattedAmount', 'purchaseDate', 'mainDescription', 'additionalDescription', 'foreignCash', 'cid', 'added_on')
Transaction = collections.namedtuple('Transaction', TRANSACTION_FIELD_NAMES)

Statement = collections.namedtuple('Statement', ['date', 'form', 'first_access', 'have_csv'])

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


def map_transaction_equiv(item):
	if item.postingSequence:
		return (1, item.postingSequence)
	else:
		return (2, item.signed_amount, item.purchaseDate, item.mainDescription, item.additionalDescription)


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

		for c in self.config['cc']: ## FIXME Card filter, module: param
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

	def get_transactions(self, card_no):
		card_no = CardNumber.coerce(card_no)
		csv_name = os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_CSV).format(card_no=card_no)
		entries = []

		with open(csv_name, 'r', newline='') as fp:
			reader = csv.reader(fp)
			for i, row in enumerate(reader):
				if i == 0 and row[0] == TRANSACTION_FIELD_NAMES[0]:
					continue

				data = Transaction._make(row)
				yield data


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

		if not form:
			raise Exception("No form found")

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
				scraper = CardDataScraper(self.config, self, a_elem)
				if 'cards' in self.config:
					for card_no in self.config['cards']:
						if scraper.card_no == card_no:
							yield scraper
				else:
					yield scraper

class CardDataScraper(ScraperBase):
	def __init__(self, configuration, parent, a_elem):
		super(CardDataScraper, self).__init__(configuration, parent)
		self._a_elem = a_elem
		self.card_no = CardNumber( "".join( self._a_elem.stripped_strings ) )

	def navigate_bt(self, action):
		parts = urlparse(self._a_elem['href'])
		query = parse_qs( parts.query )

		query.pop('inquiryType', None)
		for name in list(query.keys()):
			if name.startswith('bt_'):
				query.pop(name, None)

		query['bt_{0}'.format(action)] = ['do']

		new_parts = list(parts)
		new_parts[4] = urlencode(query, doseq=True)

		self.navigate(urlunparse(new_parts))

	def __repr__(self):
		return "<CardDataScraper(card_no={0!r}>".format(self.card_no)


	def synchronize_csv(self, csv_name=None):
		if csv_name is None:
			csv_name = os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_CSV).format(card_no=self.card_no)

		os.makedirs(os.path.dirname(csv_name), exist_ok=True)

		have_header = False
		old_entries = []
		changed = False

		with open(csv_name, 'a+', newline='') as fp:
			fp.seek(0)
			reader = csv.reader(fp)
			for i, row in enumerate(reader):
				if i == 0 and row[0] == TRANSACTION_FIELD_NAMES[0]:
					have_header = True
					continue

				data = Transaction._make(row)
				old_entries.append(data)

			writer = csv.writer(fp)
			if not have_header and len(old_entries) == 0:
				writer.writerow(TRANSACTION_FIELD_NAMES)

			for statement in self.get_statement_links():
				if not statement.have_csv:
					new_entries = self.get_transactions(statement.form)
					missing, expired = symmetric_difference(new_entries, old_entries, map_to_equiv=map_transaction_equiv, transform_b=Transaction._make )
					for transaction in missing:
						writer.writerow(transaction)
						old_entries.append(transaction)
						changed = True
					self.download_statement_csv(statement)

			new_entries = self.get_transactions()
			missing, expired = symmetric_difference(new_entries, old_entries, map_to_equiv=map_transaction_equiv, transform_b=Transaction._make )
			for transaction in missing:
				writer.writerow(transaction)
				old_entries.append(transaction)
				changed = True

		return changed

	def synchronize_statements(self, rest_client):
		os.makedirs(os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY).format(card_no=self.card_no), exist_ok=True)

		for statement in self.get_statement_links():
			pdf_name = os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_STATEMENT_PDF).format(card_no=self.card_no, date=statement.date)

			if not os.path.exists(pdf_name):
				pdf_content = self.fetch_statement_pdf(statement)

				if pdf_content:
					rest_client.upload_image(os.path.basename(pdf_name), pdf_content, 'application/pdf')
					with open(pdf_name, "wb") as fp:
						fp.write(pdf_content)


	def get_transactions(self, statement_form=None):
		if statement_form is None:
			self.navigate_bt('TXN')
			table = self.soup.find('table', attrs={'id': 'transactions'})

			if not table:
				return

			# Find the tabhead, then the rest of the table
			tabhead = table.find('tr', class_='tabhead')
			rows = list(tabhead.find_next_siblings('tr'))
		else:
			self.submit_form(statement_form, {}, 'bt_STMT')

			form = self.soup.find('form', attrs={'name': 'statementForm'})
			if not form:
				return
			
			current_tr = form.find_parent('tr')
			found = 0
			while current_tr:
				if len(list(current_tr.find_all('td', class_='tabhead'))) == 3:
					found = found + 1
				if found == 2:
					break
				current_tr = current_tr.find_next_sibling('tr')

			if not current_tr:
				return

			if not found == 2:
				return

			rows = list(current_tr.find_next_siblings('tr'))

		i = 0
		while i < len(rows):
			if 'tabhead' in rows[i].get('class', []):
				i = i + 1
				continue

			row_a = rows[i +0]
			row_b = rows[i +1]
			i = i + 2

			dataset = {'card_no': str(self.card_no)}

			if row_a.find('td').get('colspan', '') == '3':
				# Empty row ends list
				break
			
			# Option 1: Find the complaint form in row b which has all data in a neat, described dataset
			form = row_b.find('form')
			if form:
				for field_name in TRANSACTION_FIELD_NAMES:
					i_elem = form.find('input', attrs={'name': field_name})
					if i_elem:
						dataset[field_name] = i_elem.get('value', '').strip()

			# Option 2: parse the table rows
			else:
				dataset['postingDate'] = row_a.find_all('td')[0].string.strip()
				description = row_a.find_all('td')[1].string
				if ' / ' in description:
					dataset['mainDescription'] = description.rsplit(' / ', 1)[0].strip()
					dataset['additionalDescription'] = description.rsplit(' / ', 1)[1].strip()
				else:
					dataset['mainDescription'] = description.strip()
				dataset['amount'] = " ".join( row_a.find_all('td')[2].nobr.string.split() )
				dataset['purchaseDate'] = row_b.find_all('td')[0].string.strip()
				dataset['foreignCash'] = row_b.find_all('td')[1].nobr.string.strip()

			for field_name in TRANSACTION_FIELD_NAMES:
				dataset.setdefault(field_name, '')

			# Massage the amount: remove suffixed +/- sign and prefix it (defaulting to -)
			split_amount = dataset['amount'].strip().rsplit(None, 1)
			if len(split_amount) > 1:
				sign = '+' if split_amount[1] == '+' else '-'
			elif len(split_amount) == 1 and len(split_amount[0]) > 0 and split_amount[0][0] not in ('-', '+'):
				sign = '-'
			else:
				sign = ''
			dataset['signed_amount'] = sign+split_amount[0]
			dataset['signed_amount'] = dataset['signed_amount'].replace('.', '')

			dataset['added_on'] = datetime.now(timezone.utc).isoformat()

			yield Transaction(**dataset)

	def get_statement_links(self):
		self.navigate_bt('STMTLIST')

		table = self.soup.find('table', attrs={'id': 'bills'})
		if not table:
			return

		for form in table.find_all('form'):
			button_link = form.find('input', attrs={'name': 'bt_STMT'})
			if not button_link:
				continue

			first_access_td = form.find_parent('td').find_next_sibling('td')
			if first_access_td:
				first_access = " ".join(first_access_td.stripped_strings)
			else:
				first_access = ""

			date = normalize_date_TTMMJJJJ(button_link['value'])
			if os.path.exists(os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_STATEMENT_CSV)\
					.format(card_no=self.card_no, date=date) ):
				have_csv = True
			else:
				have_csv = False

			yield Statement(date, form, normalize_date_TTMMJJJJ(first_access), have_csv)

	def download_statement_csv(self, statement):
		self.submit_form(statement.form, {}, 'bt_STMT')

		form = self.soup.find('input', attrs={'name': 'bt_STMTSAVE'}).find_parent('form')
		self.submit_form(form, {}, 'bt_STMTSAVE')

		for a in self.soup.find_all('a'):
			if 'bt_STMTCSV' in a.get('href', ''):
				CSV_RESPONSE = self.session.get( self.resolve_url(a['href']) )

				csv_name = os.path.join(DOCUMENT_DIRECTORY, CARD_DIRECTORY, CARD_STATEMENT_CSV)\
					.format(card_no=self.card_no, date=statement.date)

				with open(csv_name, 'w') as fp:
					fp.write(CSV_RESPONSE.text)

	def fetch_statement_pdf(self, statement):
		self.submit_form(statement.form, {}, 'bt_STMT')

		form = self.soup.find('input', attrs={'name': 'bt_STMTSAVE'}).find_parent('form')
		self.submit_form(form, {}, 'bt_STMTSAVE')

		for a in self.soup.find_all('a'):
			if 'bt_STMTPDF' in a.get('href', ''):
				PDF_RESPONSE = self.session.get( self.resolve_url(a['href']) )
				return PDF_RESPONSE.content

		for elem in self.soup.find_all('font', attrs={'color': 'red'}):
			# Statement will be ready next business day
			return None

		raise Exception("Kein PDF-Download gefunden")


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

def select_last_option(request_data, form):
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

		error_div = self.soup.body.find('div', class_='msgerror')
		if error_div:
			raise LoginError(simplify_message(error_div))

	def log_out(self):
		if self.current_page:
			form = self.soup.body.find('div', class_='loginlogout').find('form')
			self.submit_form(form, {}, None, last_submit)
			self.clear_session()

	def cc_sso(self):
		# Case distinction: If there's only one card, it is automatically selected
		#  If there's two cards, a selection needs to be made:
		#  Simple way: Select and choose the first form with select field, choose last credit card

		credit_form = self.soup.body.find('select').find_parent('form')

		have_a_href = False
		for a in credit_form.find_all('a'):
			if '/sso' in a['href']:
				# Variant 1
				have_a_href = True
				break

		if not have_a_href:
			# Variant 2
			self.submit_form(credit_form, {}, None, [select_last_option, last_submit])

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



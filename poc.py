#!/usr/bin/env python3
import requests
import json
import yaml
import logging
import pprint
import os, os.path
import sys
import imapclient
import datetime
import email, email.utils
import enum
import magic
import io
import zipfile

CONFIG_DEFAULTS = {
	"lexofficeInstance": "app.lexoffice.de",
}

URLS = {
	'login': 'https://{lexofficeInstance}/grld-public/login/authorize',
	'privilege': 'https://{lexofficeInstance}/grld-rest/privilege-management/v100/privilege',
	'uploadBookkeepingVoucherImage': 'https://{lexofficeInstance}/grld-rest/voucherimageservice/1/v101/uploadBookkeepingVoucherImage/',
}

USER_AGENT = 'GITHUB_COM_HENRYK_LEXOFFICE_BELEGMAIL/43'
ACCEPTABLE_LIST = ['image/jpeg', 'application/pdf', 'image/png']
ACCEPTABLE_ZIP = ['application/zip', 'application/x-zip-compressed']
ACCEPTABLE_OCTET = 'application/octet-stream'

ZIP_RECURSION_LIMIT = 2

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

class PROCESSING_RESULT(enum.Enum):
	ERROR = 0
	UPLOADED = 1
	IGNORE = 2
	PROCESSED = 3
	OTHER = 4

class ImapReceiver(object):
	def __init__(self):
		self.c = None
		self.config = None

	def load_config(self, filename):
		with open(filename, "r") as fp:
			self.config = dict(CONFIG_DEFAULTS)
			self.config.update( yaml.load(fp) )

	def run(self):
		config = self.config["imap"]

		server = imapclient.IMAPClient(config["server"], port=config["port"], ssl=config["ssl"])
		server.login(config["username"], config["password"])

		server.debug=config.get("debug", False)

		while True:
			target_folder = "Hochgeladen {0}".format( datetime.date.today().year )
			if not server.folder_exists(target_folder):
				server.create_folder(target_folder)
				server.subscribe_folder(target_folder)

			select_info = server.select_folder('INBOX')
			if select_info[b"EXISTS"]:
				messages = server.search(['NOT', 'DELETED', 'NOT', 'SEEN'])
				response = server.fetch(messages, ['RFC822'])

				for msgid, data in response.items():
					body = data[b'RFC822']
					target = None
					result = PROCESSING_RESULT.ERROR

					try:
						message = email.message_from_bytes(body)

						result = self.handle_mail(message)

					except:
						logging.exception("Fehler beim Bearbeiten der Mail {0}".format(msgid))

					finally:
						if result is PROCESSING_RESULT.UPLOADED:
							server.add_flags(msgid, [imapclient.SEEN])
							server.copy(msgid, target_folder)
							server.delete_messages(msgid)
							server.expunge()
						elif result in (PROCESSING_RESULT.IGNORE, PROCESSING_RESULT.OTHER):
							server.remove_flags(msgid, [imapclient.SEEN])


			server.idle()
			server.idle_check(timeout=300)  # Do a normal poll every 5 minutes, just in case
			server.idle_done()

	def handle_mail(self, message):
		if not message.is_multipart():
			logging.info("Message is not multipart message")
			return PROCESSING_RESULT.OTHER

		if not self.check_access(message):
			logging.info("Message not from allowed sender or recipient")
			return PROCESSING_RESULT.IGNORE

		upload_count = 0
		error_count = 0

		for part in message.walk():
			ctype = part.get_content_type()
			name, data = None, None
			logging.info("Have %r", ctype)

			if ctype in ACCEPTABLE_LIST + ACCEPTABLE_ZIP + [ACCEPTABLE_OCTET]:
				name = part.get_filename()
				data = part.get_payload(decode=True)

			if ctype == ACCEPTABLE_OCTET:
				magic_type = magic.from_buffer(data, mime=True)
				if magic_type in ACCEPTABLE_LIST + ACCEPTABLE_ZIP:
					ctype = magic_type
				else:
					data = None

			if data:
				if ctype in ACCEPTABLE_ZIP:
					part_iter = self.handle_zip(name, ctype, data)
				else:
					part_iter = [ (name, ctype, data) ]

				for (name, ctype, data) in part_iter:
					logging.info("Have attachment %r (%s) of size %s", name, ctype, len(data))
					self.ensure_login()
					result = None
					try:
						result = self.c.upload_image(name, data, ctype)
					except:
						logging.exception("Fehler beim Hochladen des Attachments {0}".format(name))
						error_count = error_count+1

					if result:
						logging.info("Attachment hochgeladen, Ergebnis: {0}".format(result))
						upload_count = upload_count+1

		if error_count > 0:
			return PROCESSING_RESULT.ERROR

		if upload_count > 0:
			return PROCESSING_RESULT.UPLOADED

		return PROCESSING_RESULT.PROCESSED

	@staticmethod
	def handle_zip(name, ctype, data, recursion=0):
		if recursion <= ZIP_RECURSION_LIMIT:
			zio = io.BytesIO(data)
			with zipfile.ZipFile(zio) as zfile:
				for finfo in zfile.infolist():
					fdata = zfile.read(finfo)

					fctype = magic.from_buffer(fdata, mime=True)

					new_name = "{0}::{1}".format(name, finfo.filename)

					if fctype in ACCEPTABLE_LIST:
						yield (new_name, fctype, fdata)
					elif fcype in ACCEPTABLE_ZIP:
						yield from handle_zip(new_name, fctype, fdata)




	def ensure_login(self):
		# FIXME Better logic
		if not self.c:
			self.c = RestClient()
			self.c.set_config(self.config)
			self.c.login()

	def check_access(self, message):
		senders = message.get_all('from', [])
		recipients = message.get_all('to', []) + message.get_all('cc', [])

		for name, sender in email.utils.getaddresses(senders):
			for allowed_sender in self.config.get("access", {}).get("from", []):
				if sender.lower() == allowed_sender.lower():
					return True

		for name, recipient in email.utils.getaddresses(recipients):
			for allowed_recipient in self.config.get("access", {}).get("to", []):
				if recipient.lower() == allowed_recipient.lower():
					return True

		return False


class RestClient(object):
	def __init__(self):
		self.config = dict(CONFIG_DEFAULTS)
		self.session = None

	def load_config(self, filename):
		with open(filename, "r") as fp:
			self.config = dict(CONFIG_DEFAULTS)
			self.config.update( yaml.load(fp) )

	def set_config(self, config):
		self.config = dict(config)

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


if __name__ == "__main__":
	if len(sys.argv) > 1:
		c = RestClient()
		c.load_config("config.yml")

		user = c.login()
		pprint.pprint(user)

		privilege = c.privilege()
		pprint.pprint(privilege)

		response = c.upload_image(sys.argv[1])
		pprint.pprint(response)
	else:
		i = ImapReceiver()
		i.load_config("config.yml")

		i.run()

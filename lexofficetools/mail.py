import imapclient
import datetime
import email, email.utils
import enum
import magic
import io
import zipfile
import logging
from signal import SIGINT, SIGTERM
from pysigset import suspended_signals
from email.header import decode_header

from .lexoffice import RestClientUser

ACCEPTABLE_LIST = ['image/jpeg', 'application/pdf', 'image/png']
ACCEPTABLE_ZIP = ['application/zip', 'application/x-zip-compressed']
ACCEPTABLE_OCTET = 'application/octet-stream'

ZIP_RECURSION_LIMIT = 2

class PROCESSING_RESULT(enum.Enum):
	ERROR = 0
	UPLOADED = 1
	IGNORE = 2
	PROCESSED = 3
	OTHER = 4

def decode_header_value(data):
	result = []
	for text, encoding in decode_header(data):
		if hasattr(text, 'decode'):
			result.append(text.decode(encoding or 'us-ascii'))
		else:
			result.append(text)
	return "".join(result)

class ImapReceiver(RestClientUser):
	def __init__(self, configuration):
		super(ImapReceiver, self).__init__(configuration)
		self.logger = logging.getLogger('lexofficetools.mail[{0}]'.format(configuration.name))

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
				
				with suspended_signals(SIGINT, SIGTERM):
					response = server.fetch(messages, ['RFC822'])

					for msgid, data in response.items():
						body = data[b'RFC822']
						target = None
						result = PROCESSING_RESULT.ERROR

						try:
							message = email.message_from_bytes(body)

							result = self.handle_mail(message)

						except:
							self.logger.exception("Fehler beim Bearbeiten der Mail {0}".format(msgid))

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
			self.logger.info("Message is not multipart message")
			return PROCESSING_RESULT.OTHER

		if not self.check_access(message):
			self.logger.info("Message not from allowed sender or recipient")
			return PROCESSING_RESULT.IGNORE

		upload_count = 0
		error_count = 0

		for part in message.walk():
			ctype = part.get_content_type()
			name, data = None, None
			self.logger.info("Have %r", ctype)

			if ctype in ACCEPTABLE_LIST + ACCEPTABLE_ZIP + [ACCEPTABLE_OCTET]:
				name = decode_header_value( part.get_filename() )
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
					self.logger.info("Have attachment %r (%s) of size %s", name, ctype, len(data))
					self.ensure_login()
					result = None
					try:
						result = self.c.upload_image(name, data, ctype)
					except:
						self.logger.exception("Fehler beim Hochladen des Attachments {0}".format(name))
						error_count = error_count+1

					if result:
						self.logger.info("Attachment hochgeladen, Ergebnis: {0}".format(result))
						upload_count = upload_count+1

		if error_count > 0:
			return PROCESSING_RESULT.ERROR

		if upload_count > 0:
			return PROCESSING_RESULT.UPLOADED

		return PROCESSING_RESULT.PROCESSED

	def handle_zip(self, name, ctype, data, recursion=0):
		if recursion <= ZIP_RECURSION_LIMIT:
			zio = io.BytesIO(data)
			with zipfile.ZipFile(zio) as zfile:
				for finfo in zfile.infolist():
					fdata = zfile.read(finfo)

					fctype = magic.from_buffer(fdata, mime=True)

					new_name = "{0}::{1}".format(name, finfo.filename)

					if fctype in ACCEPTABLE_LIST:
						yield (new_name, fctype, fdata)
					elif fctype in ACCEPTABLE_ZIP:
						yield from self.handle_zip(new_name, fctype, fdata, recursion+1)




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

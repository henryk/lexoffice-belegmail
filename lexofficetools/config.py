import os.path
import yaml

CONFIG_DEFAULTS = {
	"lexofficeInstance": "app.lexoffice.de",
}

class ConfigParseError(Exception): pass

class Configuration(object):
	def __init__(self, parent, name):
		self._parent = parent
		self._name = name

	@property
	def _config(self):
		return self._parent.configs[self._name]

	def __getitem__(self, name):
		return self._config[name]

	def keys(self):
		return self._config.keys()

	def get(self, name, *args, **kwargs):
		return self._config.get(name, *args, **kwargs)

	@property
	def name(self):
		return self._name

class ConfigurationManager(object):
	def __init__(self):
		self.configs = dict()

	def load(self, fp):
		config = yaml.load(fp)

		if isinstance(config, dict):
			config = [
				{
					'name': os.path.basename( getattr(fp, 'name', 'default')  ).rsplit('.', 1)[0],
					'config': config,
				}
			]
		elif not isinstance(config, (tuple, list)):
			raise ConfigParseError('Konfiguration muss entweder ein Dictionary sein, oder eine Liste von Dictionaries.')

		for cfg in config:
			if not 'name' in cfg or not 'config' in cfg:
				raise ConfigParseError('Konfiguratio muss eine Liste von Dictionaries mit den Schlüsseln "name" und "config" sein.')

			self.configs[cfg['name']] = dict(CONFIG_DEFAULTS)
			self.configs[cfg['name']].update(cfg['config'])

	def configurations(self):
		for name in self.configs.keys():
			yield Configuration(self, name)

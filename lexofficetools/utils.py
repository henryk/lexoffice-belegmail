import re
import datetime

def normalize_date_TTMMJJJJ(data):
	data = "".join(data.split())
	if not data:
		return ""

	date = datetime.datetime.strptime(data, '%d.%m.%Y')
	return date.strftime('%Y-%m-%d')

def symmetric_difference(list_a, list_b, map_to_equiv=lambda x: x, transform_a=lambda a: a, transform_b=lambda b: b):

	def helper_transform(item, transform):
		t_item = transform(item)
		return (map_to_equiv(t_item), t_item, item)

	tmp_a = list(helper_transform(a, transform_a) for a in list_a)
	tmp_b = list(helper_transform(b, transform_b) for b in list_b)

	ctr_a = collections.Counter( m_a for (m_a, t_a, a) in tmp_a )
	ctr_b = collections.Counter( m_b for (m_b, t_b, b) in tmp_b )

	only_in_a = []
	only_in_b = []

	for m_a, t_a, a in tmp_a:
		if ctr_b[m_a]:
			ctr_b[m_a] -= 1
		else:
			only_in_a.append(a)

	for m_b, t_b, b in tmp_b:
		if ctr_a[m_b]:
			ctr_a[m_b] -= 1
		else:
			only_in_b.append(b)

	return only_in_a, only_in_b


class LoginError(Exception): pass

class TemporaryError(Exception): pass

class CardNumber(object):
	def __init__(self, value):
		self._value = self.normalize(value)

	@staticmethod
	def normalize(value):
		"""Normalizes a (partial) credit card number to a common format.
		'1234'                -> 'xxxxxxxxxxxx1234'
		'4277 19xx xxxx 1234' -> '427719xxxxxx1234'
		'4277*1234'           -> '4277xxxxxxxx1234'
		'4277x'               -> '4277xxxxxxxxxxxx'
		"""
		# Step 1: remove all whitespace
		value = "".join(value.split())

		# Step 2: split by non-numbers
		parts = list( re.split(r'[^0-9]+', value) )

		# Step 3: determine the number of padding chars to insert
		padding = max(0, 16 - len("".join(parts)))

		# Step 4: Assemble list of parts
		new_parts = []
		for i,part in enumerate(parts):
			if i>0 or len(parts) == 1:
				# Step 4a: Anchor right if only one part
				new_parts.append(None)
			new_parts.append(part)

		# Step 5: Count number of filler sequences
		number_fillers = len([e for e in new_parts if e is None])

		# Step 6: Fill filler sequences with placeholders
		for i, part in enumerate(new_parts):
			if part is None:
				new_parts[i] = (padding//number_fillers)*'x'

		# Step 7: Append additional placeholders to first filler
		for i,part in enumerate(new_parts):
			if part == '' or part[0] == 'x':
				new_parts[i] = part + ( max(0, 16-len("".join(new_parts))) * 'x' )
				break

		return "".join(new_parts)

	@classmethod
	def coerce(cls, value):
		if isinstance(value, int):
			value = str(value)

		if isinstance(value, cls):
			return value
		elif isinstance(value, str):
			return cls(value)
		else:
			return NotImplementedError

	def update(self, other):
		other = self.coerce(other)
		if not self == other:
			raise ValueError("Can't update unequal CardNumber objects")

		tmp = []
		for a,b in zip(self._value, other._value):
			if a == 'x' and b != 'x':
				tmp.append(b)
			else:
				tmp.append(a)

		self._value = "".join(tmp)

	def __str__(self):
		return self._value

	def __repr__(self):
		return '{0}({1!r})'.format(self.__class__.__name__, self._value)

	def __eq__(self, other):
		other = self.coerce(other)
		if not isinstance(other, CardNumber):
			return False

		for a,b in zip(self._value, other._value):
			if not (a == 'x' or b == 'x' or a == b):
				return False
		return True

	def __lt__(self, other): raise NotImplementedError
	def __le__(self, other): raise NotImplementedError
	def __gt__(self, other): raise NotImplementedError
	def __ge__(self, other): raise NotImplementedError

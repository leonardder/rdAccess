import typing
import addonHandler
from driverHandler import Driver
import api
from logHandler import log
import sys
from extensionPoints import AccumulatingDecider
from hwIo.ioThread import IoThread
from abc import abstractmethod

if typing.TYPE_CHECKING:
	from ....lib import configuration
	from ....lib import namedPipe
	from ....lib import protocol
else:
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	configuration = addon.loadModule("lib.configuration")
	namedPipe = addon.loadModule("lib.namedPipe")
	protocol = addon.loadModule("lib.protocol")


MAX_TIME_SINCE_INPUT_FOR_REMOTE_SESSION_FOCUS = 200


class RemoteHandler(protocol.RemoteProtocolHandler):
	_dev: namedPipe.NamedPipeBase
	decide_remoteDisconnect: AccumulatingDecider
	_remoteSessionhasFocus: typing.Optional[bool] = None
	_driver: Driver
	_abstract__driver = True

	def _get__driver(self) -> Driver:
		raise NotImplementedError

	def __new__(cls, *args, **kwargs):
		obj = super().__new__(cls, *args, **kwargs)
		obj.decide_remoteDisconnect = AccumulatingDecider(False)
		return obj

	def __init__(
			self,
			ioThread: IoThread,
			pipeName: str,
			isNamedPipeClient: bool = True,
	):
		super().__init__()
		try:
			IO = namedPipe.NamedPipeClient if isNamedPipeClient else namedPipe.NamedPipeServer
			self._dev = IO(
				pipeName=pipeName,
				onReceive=self._onReceive,
				onReadError=self._onReadError,
				ioThread=ioThread
			)
		except EnvironmentError:
			raise

		self._handleDriverChanged(self._driver)

	def event_gainFocus(self, obj):
		# Invalidate the property cache to ensure that hasFocus will be fetched again.
		# Normally, hasFocus should be cached since it is pretty expensive
		# and should never try to fetch the time since input from the remote driver
		# more than once per core cycle.
		# However, if we don't clear the cache here, the braille handler won't be enabled correctly
		# for the first focus outside the remote window.
		self.invalidateCache()
		self._remoteSessionhasFocus = None

	@protocol.attributeSender(protocol.GenericAttribute.SUPPORTED_SETTINGS)
	def _outgoing_supportedSettings(self, settings=None) -> bytes:
		if not configuration.getDriverSettingsManagement():
			return self._pickle([])
		if settings is None:
			settings = self._driver.supportedSettings
		return self._pickle(settings)

	@protocol.attributeSender(b"available*s")
	def _outgoing_availableSettingValues(self, attribute: protocol.AttributeT) -> bytes:
		if not configuration.getDriverSettingsManagement():
			return self._pickle({})
		name = attribute.decode("ASCII")
		return self._pickle(getattr(self._driver, name))

	@protocol.attributeReceiver(protocol.SETTING_ATTRIBUTE_PREFIX + b"*")
	def _incoming_setting(self, attribute: protocol.AttributeT, payLoad: bytes):
		assert len(payLoad) > 0
		return self._unpickle(payLoad)

	@_incoming_setting.updateCallback
	def _setIncomingSettingOnDriver(self, attribute: protocol.AttributeT, value: typing.Any):
		if not configuration.getDriverSettingsManagement():
			return
		name = attribute[len(protocol.SETTING_ATTRIBUTE_PREFIX):].decode("ASCII")
		setattr(self._driver, name, value)

	@protocol.attributeSender(protocol.SETTING_ATTRIBUTE_PREFIX + b"*")
	def _outgoing_setting(self, attribute: protocol.AttributeT):
		if not configuration.getDriverSettingsManagement():
			return self._pickle(None)
		name = attribute[len(protocol.SETTING_ATTRIBUTE_PREFIX):].decode("ASCII")
		return self._pickle(getattr(self._driver, name))

	hasFocus: bool

	def _get_hasFocus(self) -> bool:
		remoteProcessHasFocus = api.getFocusObject().processID == self._dev.pipeProcessId
		if not remoteProcessHasFocus:
			return remoteProcessHasFocus
		if self._remoteSessionhasFocus is not None:
			return self._remoteSessionhasFocus
		log.debug("Requesting time since input from remote driver")
		attribute = protocol.GenericAttribute.TIME_SINCE_INPUT
		self.requestRemoteAttribute(attribute)
		return False

	@protocol.attributeReceiver(protocol.GenericAttribute.TIME_SINCE_INPUT, defaultValue=False)
	def _incoming_timeSinceInput(self, payload: bytes) -> int:
		assert len(payload) == 4
		return int.from_bytes(payload, byteorder=sys.byteorder, signed=False)

	@_incoming_timeSinceInput.updateCallback
	def _post_timeSinceInput(self, attribute: protocol.AttributeT, value: int):
		assert attribute == protocol.GenericAttribute.TIME_SINCE_INPUT
		self._remoteSessionhasFocus = value <= MAX_TIME_SINCE_INPUT_FOR_REMOTE_SESSION_FOCUS
		if self._remoteSessionhasFocus:
			self._handleRemoteSessionGainFocus()

	def _handleRemoteSessionGainFocus(self):
		return

	def _onReadError(self, error: int) -> bool:
		return self.decide_remoteDisconnect.decide(handler=self, error=error)

	@abstractmethod
	def _handleDriverChanged(self, driver: Driver):
		self._attributeSenderStore(
			protocol.GenericAttribute.SUPPORTED_SETTINGS,
			settings=driver.supportedSettings
		)
